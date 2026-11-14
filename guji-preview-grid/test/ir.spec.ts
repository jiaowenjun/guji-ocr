// Guji IR v3 验收套件：核心原则是「骨架独立」——去掉全部 overlay 后占格与换行
// 不变；合字/跨行书名/无 src 渲染/码点区间等按 v3 契约验收（不再复刻旧解析器
// 的特殊行为）。TXT 与旧口径的一致性作为目标性回归断言保留。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { parsePages } from "../src/parser/parse-pages";
import { gj2ir } from "../src/ir/gj2ir";
import { layout3 } from "../src/ir/layout3";
import { irToText } from "../src/ir/text";
import { highlightAt, bandCursorTarget, buildCharIndex, charHighlightAt } from "../src/ir/linkage";
import type { IRDocument } from "../src/ir/types";
import yibu from "../src/samples/kangxi-yibu.gj?raw";

function stable(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stable).join(",")}]`;
  if (v && typeof v === "object") {
    return `{${Object.entries(v as Record<string, unknown>)
      .filter(([, x]) => x !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([k, x]) => `${JSON.stringify(k)}:${stable(x)}`)
      .join(",")}}`;
  }
  return JSON.stringify(v) ?? "null";
}

/** 去掉全部 overlay 与 src（模拟无 .gj 源/纯骨架输入） */
function skeletonOnly(doc: IRDocument): IRDocument {
  return JSON.parse(
    JSON.stringify({ version: doc.version, meta: doc.meta, pages: doc.pages }),
  ) as IRDocument;
}

const corpus: Array<[string, string]> = [
  ["17 页样例全文", yibu],
  [
    "330 爬取草稿",
    readFileSync(
      fileURLToPath(new URL("../../kangxi-gold/annotations/0330.gj", import.meta.url)),
      "utf-8",
    ),
  ],
];

describe("v3 骨架独立（核心原则）", () => {
  it("去掉全部 overlay 与 src，pages 逐字节不变；layout3 输出不变", () => {
    for (const [, text] of corpus) {
      const doc = gj2ir(text);
      const stripped = skeletonOnly(doc);
      expect(stable(stripped.pages)).toBe(stable(doc.pages));
      expect(stable(layout3(stripped))).toBe(stable(layout3(doc)));
    }
  });

  it("圆圈是纯 overlay：#(增：甲 与 #增：甲 骨架相同（标点隔开裸字连写语境）", () => {
    const noSrc = (d: IRDocument) =>
      JSON.parse(JSON.stringify(d.pages), (k, v) => (k === "src" || k === "cpSrcs" ? undefined : v));
    const a = gj2ir("@1\n\n#(增：甲\n");
    const b = gj2ir("@1\n\n#增：甲\n");
    expect(stable(noSrc(a))).toBe(stable(noSrc(b)));
    expect(a.overlays).toHaveLength(1);
    expect(a.overlays[0]).toMatchObject({ kind: "circle" });
    expect(b.overlays).toHaveLength(0);
  });

  it("糖：#(增甲 ≡ #(增)#甲（带圈后裸字=字头）", () => {
    const noSrc = (d: IRDocument) =>
      JSON.parse(JSON.stringify(d.pages), (k, v) => (k === "src" || k === "cpSrcs" ? undefined : v));
    const a = gj2ir("@1\n\n#(增甲\n");
    const b = gj2ir("@1\n\n#(增)#甲\n");
    expect(stable(noSrc(a))).toBe(stable(noSrc(b)));
    expect(a.overlays).toHaveLength(1);
    expect(b.overlays).toHaveLength(1);
  });

  it("书名括号不产生骨架内容：【A】b 与 Ab 骨架相同", () => {
    const a = gj2ir("@2\n\n#甲【書】音義\n");
    const b = gj2ir("@2\n\n#甲書音義\n");
    const stripNo = (d: IRDocument) =>
      JSON.parse(JSON.stringify(d.pages), (k, v) => (k === "src" || k === "cpSrcs" ? undefined : v));
    expect(stable(stripNo(a))).toBe(stable(stripNo(b)));
  });

  it("跨行书名不吞换行：三行各为小行，书名 overlay 引用三行", () => {
    const doc = gj2ir("@4\n\n【開於甲\n帶內折行\n後段】終\n");
    const band = doc.pages[0].bands[0];
    expect(band.lines).toHaveLength(3);
    expect(band.lines.map((l) => l.elements.map((e) => e.text).join(""))).toEqual([
      "開於甲",
      "帶內折行",
      "後段終",
    ]);
    const books = doc.overlays.filter((o) => o.kind === "book-title");
    expect(books).toHaveLength(1);
    expect(books[0]).toMatchObject({ spans: [{ range: [0, 3] }, { range: [0, 4] }, { range: [0, 2] }] });
    // 布局：三个小行各占一列（k=3），未被书名吞并
    const laid = layout3(doc)[0];
    const runCols = new Set(laid.bands[0].items.filter((i) => i.kind === "run").map((i) => i.c));
    expect(runCols.size).toBe(3);
  });

  it("相邻书名保持各自身份", () => {
    const doc = gj2ir("@5\n\n【甲】子【乙】丑\n");
    const books = doc.overlays.filter((o) => o.kind === "book-title");
    expect(books).toHaveLength(2);
    expect(books[0].spans[0].range).toEqual([0, 1]);
    expect(books[1].spans[0].range).toEqual([2, 3]);
  });
});

describe("v3 合字", () => {
  it("#(十一)：一个大字格、两个文本字符；圆圈为 overlay", () => {
    const doc = gj2ir("@6\n\n#甲#(十一)：音義\n");
    const els = doc.pages[0].bands[0].lines[0].elements;
    const lig = els.find((e) => e.ligature);
    expect(lig).toMatchObject({ class: "large", text: "十一" });
    const laid = layout3(doc)[0];
    const band = laid.bands[0];
    const largeItems = band.items.filter((i) => i.kind === "large");
    // 甲 + 合字 = 2 个大字格；十一 为第 2 个；音義 小字组再占 2 行
    expect(band.rows).toBe(6);
    expect(largeItems).toHaveLength(2);
    expect(doc.overlays.some((o) => o.kind === "circle")).toBe(true);
    // 文本抽取保留两个字符
    expect(irToText(doc)).toContain("十一");
  });
});

describe("v3 标题入骨架与码点区间", () => {
  it("标题物化为逐字大字，层级为元数据；layout 顶部按层级缩进", () => {
    const doc = gj2ir("@7\n\n### 一部\n\n正文\n");
    const head = doc.pages[0].bands[0];
    expect(head.level).toBe(3);
    expect(head.lines[0].elements.map((e) => e.text)).toEqual(["一", "部"]);
    const laid = layout3(doc)[0];
    expect(laid.bands[0].items[0]).toMatchObject({ r: 4, c: 0, text: "一" }); // 缩进 = 3-1
  });

  it("扩展 B 区字符按码点计（range 不切开代理对）", () => {
    const doc = gj2ir("@8\n\n𠀤甲【書】乙\n");
    const books = doc.overlays.filter((o) => o.kind === "book-title");
    expect(books[0].spans[0].range).toEqual([2, 3]); // 𠀤(1) 甲(1) 書 0-based=2
    const line = doc.pages[0].bands[0].lines[0];
    expect([...line.elements.map((e) => e.text).join("")][2]).toBe("書");
  });
});

describe("v3 语料回归（目标性断言）", () => {
  it("阅读序文本与旧 pageToText 口径逐字符一致（17 页 + 330）", () => {
    const oldText = (t: string) => {
      const pages = parsePages(t);
      const lineText = (line: unknown) =>
        ("c" in (line as object) ? (line as { c: unknown[] }).c : [line])
          .map((b) => (b as { t?: string }).t ?? "")
          .join("");
      return pages.map((p) => p.l.map(lineText).join("\n") + "\n").join("");
    };
    for (const [, text] of corpus) {
      expect(irToText(gj2ir(text))).toBe(oldText(text));
    }
  });

  it("页/大行数与旧解析器一致（结构层面对齐）", () => {
    const doc = gj2ir(yibu);
    const parsed = parsePages(yibu);
    expect(doc.pages.map((p) => p.no)).toEqual(parsed.map((p) => p.p));
    for (const page of doc.pages) {
      expect(page.bands.length).toBe(parsed.find((p) => p.p === page.no)!.l.length);
    }
  });
});

describe("v3 联动", () => {
  const doc = gj2ir(yibu);

  it("光标 → 大行（间隙取前行；页声明行不高亮）", () => {
    const band0 = doc.pages[0].bands.find((b) => b.src)!;
    expect(highlightAt(doc, band0.src![0] + 5)?.band?.index).toBeDefined();
    const page313 = doc.pages.find((p) => p.no === 313)!;
    expect(highlightAt(doc, page313.src![0] + 1).band).toBeNull();
    expect(highlightAt(doc, page313.src![0] - 1)?.band?.page).toBe(312);
  });

  it("光标 → 书名 overlay id（跨行区间两侧均命中）", () => {
    const books = doc.overlays.filter((o): o is Extract<typeof o, { kind: "book-title" }> => o.kind === "book-title");
    const wrap = books.find((o) => o.src && o.spans.length >= 2)!;
    expect(highlightAt(doc, wrap.src![0] + 2).book).toBe(wrap.id);
    expect(highlightAt(doc, wrap.src![1] - 2).book).toBe(wrap.id);
    expect(highlightAt(doc, 0).book).toBeNull();
  });

  it("点击行 → 光标落在首个产出字符后（单字联动随即点亮该行首字）", () => {
    const band = doc.pages[0].bands.find((b) => b.lines.some((l) => (l.cpSrcs ?? []).length > 0))!;
    const target = bandCursorTarget(doc, yibu, doc.pages[0].no, band.ord);
    expect(target).not.toBeNull();
    const ch = charHighlightAt(doc, buildCharIndex(doc), yibu, target);
    expect(ch).not.toBeNull();
    // 命中元素属于被点击的大行（cell 指其行；large 指其元素所在行）
    const lineId = ch!.kind === "cell" ? ch!.lineId : band.lines.find((l) => l.elements.some((e) => e.id === ch!.elId))!.id;
    expect(band.lines.some((l) => l.id === lineId)).toBe(true);
  });
});

describe("v3 单字联动（光标前一字符 → 字格）", () => {
  const sample = "@10\n\n#𠀤甲【史記】音義。\n\n#(十一)古文\n\n@11\n\n*續上行\n";
  const doc = gj2ir(sample);
  const index = buildCharIndex(doc);
  const at = (needle: string) => sample.indexOf(needle) + needle.length; // needle 后的光标
  const l0 = doc.pages[0].bands[0].lines[0].id; // #𠀤甲【史記】音義。
  const l1 = doc.pages[0].bands[1].lines[0].id; // #(十一)古文

  it("小字：光标在「義」后 → 该行第 5 码点字格", () => {
    const ch = charHighlightAt(doc, index, sample, at("義"));
    expect(ch).toEqual({ kind: "cell", lineId: l0, cp: 5 }); // 𠀤甲史記音義 → 義=5
  });

  it("清洗字符回退：光标在「。」后 → 定位到「。」（cp 6）；渲染层经 rawOffsets 再回退到「義」", () => {
    // 两层回退：联动层回退到前一产出字符（标点在 canonical 有码点但被清洗不占格），
    // 渲染层（MatrixPages）找不到 rawOffsets 精确条目时取 ≤cp 的最大偏移 = 前一渲染字
    const ch = charHighlightAt(doc, index, sample, at("。"));
    expect(ch).toEqual({ kind: "cell", lineId: l0, cp: 6 });
    const run = layout3(doc)[0].bands[0].items.find(
      (i) => i.kind === "run" && i.lineId === l0,
    )!;
    const k = (run.rawOffsets ?? []).filter((o) => o <= 6).length - 1;
    expect(run.cells![k]).toBe("義");
  });

  it("书名括号回退：光标在「】」后 → 前一渲染字「記」", () => {
    const ch = charHighlightAt(doc, index, sample, at("】"));
    expect(ch).toEqual({ kind: "cell", lineId: l0, cp: 3 });
  });

  it("扩展 B 区大字（代理对）：光标在「𠀤」后 → 该大字格", () => {
    const els = doc.pages[0].bands[0].lines[0].elements;
    const ch = charHighlightAt(doc, index, sample, at("𠀤"));
    expect(ch).toEqual({ kind: "large", elId: els[0].id });
  });

  it("token 内部：光标在「#(」与内文之间 → 回退前一行末字「。」；在内文后 → 合字整格", () => {
    const els = doc.pages[0].bands[1].lines[0].elements;
    // 「(」不产出字符 → 回退到上一行末位产出字「。」（canonical cp 6；渲染层再回退「義」）
    expect(charHighlightAt(doc, index, sample, at("#("))).toEqual({
      kind: "cell",
      lineId: l0,
      cp: 6,
    });
    expect(charHighlightAt(doc, index, sample, at("十"))).toEqual({
      kind: "large",
      elId: els.find((e) => e.ligature)!.id,
    });
  });

  it("跨行/跨大行回退：光标在行首或 @页声明行内 → 前一大行末字", () => {
    const atLine2 = sample.indexOf("*續上行");
    expect(charHighlightAt(doc, index, sample, atLine2)).toEqual({ kind: "cell", lineId: l1, cp: 3 }); // 古文末字「文」
    expect(charHighlightAt(doc, index, sample, at("@11"))).toEqual({ kind: "cell", lineId: l1, cp: 3 });
  });

  it("文件头与空光标 → null", () => {
    expect(charHighlightAt(doc, index, sample, 0)).toBeNull();
    expect(charHighlightAt(doc, index, sample, null)).toBeNull();
  });

  it("全语料：每个产出字符后的光标都定位到其所在行", () => {
    for (const [, text] of corpus) {
      const d = gj2ir(text);
      const idx = buildCharIndex(d);
      for (const e of idx) {
        const len = String.fromCodePoint(text.codePointAt(e.src)!).length;
        const ch = charHighlightAt(d, idx, text, e.src + len);
        expect(ch).not.toBeNull();
        const lineId =
          ch!.kind === "cell"
            ? ch!.lineId
            : d.pages.flatMap((p) => p.bands).flatMap((b) => b.lines).find((l) => l.elements.some((el) => el.id === ch!.elId))!.id;
        expect(lineId).toBe(e.lineId);
      }
    }
  });
});

describe("v3 JSON 序列化稳定", () => {
  it("round-trip 无损", () => {
    const doc = gj2ir("@9\n\n#甲【書】音義\n");
    const revived: IRDocument = JSON.parse(JSON.stringify(doc));
    expect(stable(revived)).toBe(stable(doc));
    expect(revived.meta.rangeUnit).toBe("codepoint");
    expect(revived.meta.srcUnit).toBe("utf-16");
  });
});

// ---- 字头簇糖（2026-11-14）：糖 ↔ 长式骨架/占格/文本三等价 ----
// 语法：#(五)#(增)#𠂂 ≡ #(五)(增)𠂂；#(三)#丹古文#𠁿#㣋 ≡ #(三)丹，古文：𠁿㣋
// （，：可省；标记两侧标点为小字内容，TXT 经 profile 剔除与长式一致）
describe("v3 字头簇糖", () => {
  const noSrc = (d: IRDocument) =>
    JSON.parse(JSON.stringify(d.pages), (k, v) => (k === "src" || k === "cpSrcs" ? undefined : v));
  const pairs: Array<[string, string]> = [
    ["#(五)#(增)#𠂂", "#(五)(增)𠂂"],
    ["#(五)#(增)#𠂂", "#(五)(增)#𠂂"],
    ["#(十一)#(增)#𠁴", "#(十一)(增)𠁴"],
    ["#(三)#丹古文#𠁿#㣋", "#(三)丹，古文：𠁿㣋"],
    ["#(三)#丹古文#𠁿#㣋", "#(三)丹古文𠁿㣋"],
    ["#(四)#且古文：#𠀇、#𠀃", "#(四)且，古文：𠀇、𠀃"],
    ["#(四)#且古文：#𠀇、#𠀃", "#(四)且古文：𠀇、𠀃"],
    ["#一古文#弌", "#一，古文：弌"],
    ["#上古文#丄、#𠄞", "#上，古文：丄、𠄞"],
    ["#世古文：#卋", "#世，古文：卋"],
    ["#(增)#𠀃", "#(增)𠀃"],
    ["#丅、#𠄟", "#丅、𠄟"],
    ["古文：#㘳", "古文：㘳"],
    ["#(二)#万", "#(二)万"],
  ];

  // 骨架比对口径：小字文本按 profile 清洗（糖形「，古文：」的标点是小字内容，
  // 渲染/评测口径剔除后与长式「古文」同归）；大字元素原样；src/cpSrcs 剥除
  // （源偏移随拼写长度漂移，非骨架事实）
  const cleanedPages = (d: IRDocument) => {
    const doc = JSON.parse(JSON.stringify(d), (k, v) =>
      k === "src" || k === "cpSrcs" ? undefined : v,
    );
    for (const p of doc.pages)
      for (const b of p.bands)
        for (const l of b.lines)
          for (const e of l.elements)
            if (e.class === "small")
              e.text = [...e.text]
                .map((ch) => (ch === "◎" || ch === "〇" ? "○" : ch))
                .filter((ch) => !"。，·\":：、《》".includes(ch))
                .join("");
    return doc.pages;
  };
  // layout 比对口径：剔除 rawOffsets/cpStart（行内码点偏移随源形漂移，非占格事实）
  const laidCells = (d: IRDocument) =>
    JSON.parse(JSON.stringify(layout3(d)), (k, v) =>
      k === "rawOffsets" || k === "cpStart" ? undefined : v,
    );

  it("糖 ↔ 长式：骨架（清洗口径 + 去 src）相同", () => {
    for (const [long, sugar] of pairs) {
      const a = gj2ir(`@1\n\n${long}\n`);
      const b = gj2ir(`@1\n\n${sugar}\n`);
      expect(stable(cleanedPages(b)), `${sugar} vs ${long}`).toBe(stable(cleanedPages(a)));
    }
  });

  it("糖 ↔ 长式：layout3 占格与换行相同（剔除码点偏移）", () => {
    for (const [long, sugar] of pairs) {
      const a = gj2ir(`@1\n\n${long}\n`);
      const b = gj2ir(`@1\n\n${sugar}\n`);
      expect(stable(laidCells(b)), `${sugar}`).toBe(stable(laidCells(a)));
    }
  });

  it("糖 ↔ 长式：阅读序文本相同（标点经 profile 剔除）", () => {
    for (const [long, sugar] of pairs) {
      expect(irToText(gj2ir(`@1\n\n${sugar}\n`)), `${sugar}`).toBe(irToText(gj2ir(`@1\n\n${long}\n`)));
    }
  });

  it("糖 ↔ 长式：圆圈 overlay 数目一致", () => {
    for (const [long, sugar] of pairs) {
      const cs = (t: string) => gj2ir(`@1\n\n${t}\n`).overlays.filter((o) => o.kind === "circle").length;
      expect(cs(sugar), `${sugar}`).toBe(cs(long));
    }
  });

  it("反例：普通 #X 后裸字不连大（#丸俗 → 俗为小字）；正文「古文」不误判", () => {
    const a = gj2ir("@1\n\n#丸俗\n");
    expect(a.pages[0].bands[0].lines[0].elements.map((e) => `${e.class}:${e.text}`)).toEqual([
      "large:丸",
      "small:俗",
    ]);
    // 【字彙補】隔开：古文下 为正文小字
    const b = gj2ir("@1\n\n#丅【字彙補】古文下\n");
    expect(b.pages[0].bands[0].lines[0].elements.map((e) => `${e.class}:${e.text}`)).toEqual([
      "large:丅",
      "small:字彙補古文下",
    ]);
    // 折行把正文「古文酉」折到行首：无冒号不认标记
    const c = gj2ir("@1\n\n古文酉，从丣。\n");
    expect(c.pages[0].bands[0].lines[0].elements.map((e) => `${e.class}:${e.text}`)).toEqual([
      "small:古文酉，从丣。",
    ]);
    // 行首承接形须带冒号：古文：㘳 ≡ 古文：#㘳
    const d1 = gj2ir("@1\n\n古文：㘳\n");
    const d2 = gj2ir("@1\n\n古文：#㘳\n");
    expect(stable(noSrc(d1))).toBe(stable(noSrc(d2)));
  });

  it("速记/全角在糖续写中同样生效：#(5)（Z）𠂂 ≡ #(五)#(增)#𠂂", () => {
    const a = gj2ir("@1\n\n#(5)(Z)𠂂\n");
    const b = gj2ir("@1\n\n#(五)#(增)#𠂂\n");
    expect(stable(noSrc(a))).toBe(stable(noSrc(b)));
  });
});

describe("v3 字头簇糖（混排回归）", () => {
  it("糖行与释义混排：与旧解析器阅读序逐字符一致（小字 frag 先入列保序）", () => {
    const page = "@1\n\n用安息。*又通作垸。\n#(三)丹，古文：𠁿㣋\n#(五)(增)𠂂\n【唐韻】都寒切。\n";
    const oldText = (t: string) => {
      const pages = parsePages(t);
      const lineText = (line: unknown) =>
        ("c" in (line as object) ? (line as { c: unknown[] }).c : [line])
          .map((b) => (b as { t?: string }).t ?? "")
          .join("");
      return pages.map((p) => p.l.map(lineText).join("\n") + "\n").join("");
    };
    expect(irToText(gj2ir(page))).toBe(oldText(page));
  });
});
