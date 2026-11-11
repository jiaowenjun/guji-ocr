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
