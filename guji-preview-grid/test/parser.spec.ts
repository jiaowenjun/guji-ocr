// 解析器测试：移植自 vscode-guji-preview 后的行为契约
// fixtures/*.expected.json 由原插件解析器（未改动）现场生成，作为移植等价性的权威期望值
import { describe, expect, it } from "vitest";
import yibuExpected from "./fixtures/kangxi-yibu.expected.json";
import expected0312 from "./fixtures/kangxi-0312.expected.json";
import { parseInline } from "../src/parser/parse-inline";
import { parseLine } from "../src/parser/parse-line";
import { parsePages } from "../src/parser/parse-pages";
import { split } from "../src/parser/split-line";
import sample0312 from "../src/samples/kangxi-0312.gj?raw";
import sampleYibu from "../src/samples/kangxi-yibu.gj?raw";

describe("split", () => {
  it("按空行切分大行，剔除注释与标点", () => {
    const chunks = split("// 页眉\n\n@1\n\n一行文字\n\n// 备注行\n\n另一行");
    expect(chunks).toEqual(["@1", "一行文字", "另一行"]);
  });

  it("剔除 CJK 标点", () => {
    expect(split("道立於一。造分天地，化成萬物")).toEqual([
      "道立於一造分天地化成萬物",
    ]);
  });

  it("◎〇 归一为 ○，全角空格转为 *", () => {
    expect(split("◎甲〇乙　丙")).toEqual(["○甲○乙*丙"]);
  });

  it("== 分隔条之前的内容被整段丢弃", () => {
    expect(split("头部信息\n===\n@1\n\n正文")).toEqual(["@1", "正文"]);
  });

  it("注释与内容之间无空行时会并入同一大行（原实现行为）", () => {
    // "//..." 至行尾被剔除，但大行首部残留的换行不再 trim
    expect(split("// 页眉\n@1")).toEqual(["\n@1"]);
  });
});

describe("parseLine", () => {
  it("@数字 识别为页码声明", () => {
    expect(parseLine("@312")).toEqual({ page: 312 });
  });

  it("#/##/### 识别为整行大字及缩进", () => {
    expect(parseLine("# 康熙字典")).toEqual({
      t: "康熙字典",
      si: "large",
      i: 0,
    });
    expect(parseLine("## 子集上")).toEqual({ t: "子集上", si: "large", i: 1 });
    expect(parseLine("### 一部")).toEqual({ t: "一部", si: "large", i: 2 });
  });

  it("单独 # 为空大字列", () => {
    expect(parseLine("#")).toEqual({ st: "empty" });
  });
});

describe("parseInline", () => {
  it("行内大字、小字、书名", () => {
    expect(parseInline("#一古文#弌【唐韻】")).toEqual([
      { t: "一", si: "large" },
      { t: "古文" },
      { t: "弌", si: "large" },
      { t: "唐韻", st: "book" },
    ]);
  });

  it("单字带圈大字写作 #(一（不闭合，实际语料形态）", () => {
    expect(parseInline("#(一")).toEqual([
      { t: "一", si: "large", st: "circle" },
    ]);
  });

  it("两字合成的带圈大字 #(AB)", () => {
    expect(parseInline("#(AB)")).toEqual([
      { t: "AB", si: "large", st: "circle" },
    ]);
  });

  it("#( 后跟多字时仅取一字符入圈，其余为小字（原实现行为）", () => {
    expect(parseInline("#(一口")).toEqual([
      { t: "一", si: "large", st: "circle" },
      { t: "口" },
    ]);
  });

  it("单字后多写的右括号会残留为小字（原实现行为）", () => {
    expect(parseInline("#(一)")).toEqual([
      { t: "一", si: "large", st: "circle" },
      { t: ")" },
    ]);
  });

  it("换行产生 br 块", () => {
    expect(parseInline("甲乙\n丙丁")).toEqual([
      { t: "甲乙" },
      { st: "br" },
      { t: "丙丁" },
    ]);
  });

  it("跨行书名拆为 start/br/end", () => {
    expect(parseInline("【說文\n惟初")).toEqual([
      { t: "說文", st: "book-start" },
      { st: "br" },
      { t: "惟初", st: "book-middle" },
    ]);
  });

  it("* 转为空格并入小字片段", () => {
    expect(parseInline("甲*乙")).toEqual([{ t: "甲 乙" }]);
  });
});

describe("parsePages", () => {
  it("@ 之前的内容被丢弃", () => {
    const pages = parsePages("游离内容\n\n@1\n\n正文");
    expect(pages).toHaveLength(1);
    expect(pages[0].p).toBe(1);
  });

  it("0312 示例与原插件解析结果逐字一致", () => {
    const pages = parsePages(sample0312);
    expect(pages).toEqual(expected0312);
  });

  it("一部示例与原插件解析结果逐字一致（17 页）", () => {
    const pages = parsePages(sampleYibu);
    expect(pages).toHaveLength(17);
    expect(pages).toEqual(yibuExpected);
  });
});

describe("输入规范化（全角括号与速记）", () => {
  const eq = (std: string, ext: string) =>
    it(`${ext.slice(0, 10)} ≡ ${std.slice(0, 10)}`, () => {
      const page = (t: string) => JSON.stringify(parsePages(`@1\n\n${t}\n`));
      expect(page(ext)).toBe(page(std));
    });
  eq("#(增) 音義", "#（增） 音義"); // 全角闭 → 半角闭
  eq("#(增 音義", "#（增 音義"); // 全角开
  eq("#(增) 音義", "#(z) 音義"); // z 速记
  eq("#(增) 音義", "#（z） 音義"); // z 全角速记
  eq("#(十五) 音義", "#(15) 音義"); // 数字速记
  eq("#(十五) 音義", "#（15） 音義");
  eq("#(一) 音義", "#（1） 音義");
  eq("#(十) 音義", "#（10） 音義"); // 10→十（长度变化的用例）
  it("#(z) 的 IR mark 文本为「增」", async () => {
    const { gj2ir } = await import("../src/ir/gj2ir");
    const doc = gj2ir("@2\n\n#(z)#(15)音義\n");
    const marks = doc.pages[0].bands[0].lines.flatMap((l) => l.elements).filter((e) => e.class === "large");
    expect(marks.map((m) => m.text)).toEqual(["增", "十五"]);
  });
});

// 校对格式化 formatGj：补全 #(X 右括号 + 字头组独占一行（@335 排版）
// 不变量口径：折行只改行结构，字符流/大字序列/圆圈与书名 overlay/带数不变
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { formatGj } from "../src/parser/split-line";
import { gj2ir } from "../src/ir/gj2ir";
import type { IRDocument } from "../src/ir/types";

describe("formatGj 规则", () => {
  const fmt = (s: string) => formatGj(`@1\n\n${s}\n`);

  it("#(X → #(X)：补右括号（1/2 字内），已闭合不重复", () => {
    expect(fmt("#(增#𠁦 音義").split("\n")).toEqual(["@1", "", "#(增)#𠁦", "音義", ""]);
    expect(fmt("#(十一 音義")).toContain("#(十一)");
    expect(fmt("#(十五) 音義")).not.toContain("))");
  });

  it("字头组独占一行：#A / #(A) / #A古文#B / #(A)#B / 多token", () => {
    expect(fmt("去聲。#丮【唐韻】几劇").split("\n"))
      .toEqual(["@1", "", "去聲。", "#丮", "【唐韻】几劇", ""]);
    expect(fmt("#丯【廣韻】拜切").split("\n"))
      .toEqual(["@1", "", "#丯", "【廣韻】拜切", ""]);
    expect(fmt("非。#丰古文#𫵮【集韻】符風").split("\n"))
      .toEqual(["@1", "", "非。", "#丰古文#𫵮", "【集韻】符風", ""]);
    expect(fmt("丨部，非。#(三)#中古文#𠁧#𠁩【唐韻】陟弓切").split("\n"))
      .toEqual(["@1", "", "丨部，非。", "#(三)#中古文#𠁧#𠁩", "【唐韻】陟弓切", ""]);
  });

  it("异体并列 #丅、#𠄟 为一组（、为组内分隔符，不拆三行）", () => {
    expect(fmt("文#丅、#𠄟【廣韻】胡雅切").split("\n"))
      .toEqual(["@1", "", "文", "#丅、#𠄟", "【廣韻】胡雅切", ""]);
  });

  it("字头后注音冒号跟随大字同行（#与: 独占一行，冒号不分到下一行）", () => {
    expect(fmt("#与:【廣韻】【集韻】𠀤同與").split("\n"))
      .toEqual(["@1", "", "#与:", "【廣韻】【集韻】𠀤同與", ""]);
    expect(fmt("#丏：【廣韻】彌殄切").split("\n"))
      .toEqual(["@1", "", "#丏：", "【廣韻】彌殄切", ""]);
  });

  it("古文跨 band 断开：尾部半个「古」并入字头组，不拆头（#下古↵文#丅）", () => {
    expect(fmt("#下古")).toBe("@1\n\n#下古\n");
    expect(fmt("#丁古文")).toBe("@1\n\n#丁古文\n");
  });

  it("行尾 # (增 标记：补括号并独立成行（仍在本 band 内折行）", () => {
    expect(fmt("遣花開。*【正字通】或作㭍。#(增").split("\n"))
      .toEqual(["@1", "", "遣花開。*【正字通】或作㭍。", "#(增)", ""]);
  });

  it("首尾空行与注释行删除，EOF 单换行；中间的不动", () => {
    expect(formatGj("\n\n// 页首注\n@1\n\n釋文。\n// 页中注保留\n\n釋文二。\n\n// 页尾注\n\n"))
      .toBe("@1\n\n釋文。\n// 页中注保留\n\n釋文二。\n");
    expect(formatGj("  // 缩进注释  \n@1\n\n正文  ")).toBe("@1\n\n正文\n");
    expect(formatGj("\n \n//\n")).toBe("");
  });

  it("标题行与注释不动；已是独占一行的不变；幂等", () => {
    expect(fmt("# 一部 #甲")).toBe(`@1\n\n# 一部 #甲\n`);
    expect(fmt("釋文。 // 註：#甲不動")).toBe(`@1\n\n釋文。 // 註：#甲不動\n`);
    expect(fmt("#(增)#𠁦\n【字彙補】籀")).toBe(`@1\n\n#(增)#𠁦\n【字彙補】籀\n`);
    const once = fmt("去聲。#丮【唐韻】几劇");
    expect(formatGj(once)).toBe(once);
  });
});

describe("formatGj 全语料不变量：字符流/大字/overlay/带数不变", () => {
  const dir = fileURLToPath(new URL("../../kangxi-gold/annotations", import.meta.url));
  const files = readdirSync(dir).filter((f) => f.endsWith(".gj"));

  const charStream = (doc: IRDocument) =>
    doc.pages
      .flatMap((p) => p.bands.flatMap((b) => b.lines.flatMap((l) => l.elements.map((e) => e.text))))
      .join("")
      .replace(/\s/g, "");
  const largeSeq = (doc: IRDocument) =>
    JSON.stringify(
      doc.pages.flatMap((p) =>
        p.bands.flatMap((b) => b.lines.flatMap((l) => l.elements.filter((e) => e.class === "large").map((e) => e.text))),
      ),
    );
  const bandCounts = (doc: IRDocument) =>
    JSON.stringify(doc.pages.map((p) => p.bands.length));
  const overlayKinds = (doc: IRDocument) =>
    JSON.stringify(doc.overlays.map((o) => o.kind).sort());

  it("语料文件非空", () => expect(files.length).toBeGreaterThan(0));

  for (const f of files) {
    it(f, () => {
      const src = readFileSync(`${dir}/${f}`, "utf-8");
      const a = gj2ir(src);
      const b = gj2ir(formatGj(src));
      expect(charStream(b)).toBe(charStream(a));
      expect(largeSeq(b)).toBe(largeSeq(a));
      expect(bandCounts(b)).toBe(bandCounts(a));
      expect(overlayKinds(b)).toBe(overlayKinds(a));
      // 幂等：格式化两遍 = 一遍
      expect(formatGj(formatGj(src))).toBe(formatGj(src));
    });
  }
});
