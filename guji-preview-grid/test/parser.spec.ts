// .gj/2 parser and formatting contracts; old visible geometry is separately pinned by the migration fixture.
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

describe("generic line-scoped large text", () => {
  it("only numeric page markers are structural", () => {
    expect(parseLine("@312")).toEqual({ page: 312 });
    expect(parseLine("@blank")).toEqual({ c: [{ t: "@blank" }] });
    expect(parseLine("#")).toEqual({ c: [] });
  });
  it("all following content is large, including 古文, ASCII and extended Han", () => {
    expect(parseInline("前#甲古文Ab𠀀")).toEqual([
      { t: "前" }, ...[..."甲古文Ab𠀀"].map((t) => ({ t, si: "large" })),
    ]);
  });
  it("newline resets size; punctuation, blanks and book brackets do not", () => {
    const blocks = parseInline("#甲，*【乙】丙\n古文：\n#丁");
    expect(blocks.filter((b) => b.si === "large").map((b) => b.t)).toEqual(["甲", "，", " ", "乙", "丙", "丁"]);
    expect(blocks).toContainEqual({ t: "古文：" });
    expect(blocks.filter((b) => b.st === "br")).toHaveLength(2);
  });
  it("circle groups are local overlays and keep the large scope active", () => {
    expect(parseInline("#(十一)(增)甲")).toEqual([
      { t: "十一", si: "large", st: "circle" }, { t: "增", si: "large", st: "circle" }, { t: "甲", si: "large" },
    ]);
    expect(parseInline("#（15）𠀀")).toEqual(parseInline("#(十五)𠀀"));
    expect(parseInline("#(𠀀)甲")[0]).toEqual({ t: "𠀀", si: "large", st: "circle" });
    expect(parseInline("#(增甲")).toEqual(parseInline("#(增)甲"));
  });
  it("legacy PageModel is an adapter over the canonical grammar", () => {
    const content = (pages: ReturnType<typeof parsePages>) => pages.map(p => ({ p: p.p,
      text: p.l.flatMap(l => "c" in l ? l.c.map(b => b.t ?? "") : []).join("") }));
    expect(content(parsePages(sample0312))).toEqual(content(expected0312 as ReturnType<typeof parsePages>));
    expect(content(parsePages(sampleYibu))).toEqual(content(yibuExpected as ReturnType<typeof parsePages>));
    expect(parsePages(sampleYibu)).toHaveLength(17);
  });
});

import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { formatGj } from "../src/parser/split-line";
import { parseKangxiDocument as gj2ir } from "../src/datasets/kangxi";
import type { IRDocument } from "../src/ir/types";

describe("formatGj", () => {
  it("removes redundant # and closes circle tokens without moving size boundaries", () => {
    expect(formatGj("#甲#乙#丙\n古文：\n#丁")).toBe("#甲乙丙\n古文：\n#丁\n");
    expect(formatGj("#*#*甲乙")).toBe("#**甲乙\n");
    expect(formatGj("#（z）#甲")).toBe("#(增)甲\n");
    expect(formatGj("#(增#甲")).toBe("#(增)甲\n");
  });
  it("preserves ordinary words and annotations without dictionary rewrites", () => {
    expect(formatGj("#甲古文乙丙")).toBe("#甲古文乙丙\n");
    expect(formatGj("古文：㘳")).toBe("古文：\n㘳\n");
    expect(formatGj("小字#甲【書】乙 // #注")).toBe("小\n字\n#甲【書】乙 // #注\n");
  });
  it("trims only document padding without rewriting size markers", () => {
    expect(formatGj("\n// header\n@1\n\n#\n\n甲\n// tail\n")).toBe("// header\n@1\n\n甲\n// tail\n");
    const once = formatGj("#甲#乙\n古文：\n#(z)#丁");
    expect(formatGj(once)).toBe(once);
  });
});

describe("formatGj 全语料不变量：清洗字符流/大字/overlay/带数不变", () => {
  const dir = fileURLToPath(new URL("../../kangxi-gold/annotations", import.meta.url));
  const files = readdirSync(dir).filter((f) => f.endsWith(".gj"));

  // 字符流按 profile 清洗口径比对：格式化会补全「，古文：」标点（2026-11-14
  // 标准形），标点在渲染/评测口径下本就剔除——语义字符流不变
  const charStream = (doc: IRDocument) =>
    doc.pages
      .flatMap((p) => p.bands.flatMap((b) => b.lines.flatMap((l) => l.elements.map((e) => e.text))))
      .join("")
      .replace(/\s/g, "")
      .split("")
      .map((ch) => (ch === "◎" ? "○" : ch))
      .filter((ch) => !"。，·\":：、《》".includes(ch))
      .join("");
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
