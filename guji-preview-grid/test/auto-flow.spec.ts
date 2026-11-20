import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { parseKangxiDocument as parse, KANGXI_DATASET } from "../src/datasets/kangxi";
import { gj2ir } from "../src/ir/gj2ir";
import { applyBookLayout } from "../src/ir/document-layout";
import { flowDocument } from "../src/ir/auto-flow";
import { layout3 } from "../src/ir/layout3";
import { formatDocument } from "../src/components/dataset/format-document";
import { formatGj } from "../src/parser/split-line";
import { buildCharIndex, charHighlightAt, bandCursorTarget } from "../src/ir/linkage";
import { nextGujiToken } from "../src/components/editor/guji-language";
import { visibleLayout } from "./helpers/visible-layout";
import { kangxiEntries } from "../src/semantics/kangxi";
import { irToText } from "../src/ir/text";

const read = (name: string) => readFileSync(new URL(`../../docs/research/figures/kangxi-auto-flow/${name}`, import.meta.url), "utf8");
const compact = read("0382-compact.gj"), standard = read("0382-standard.gj");
const geometry = (source: string) => visibleLayout(parse(source));
const runs = (source: string) => layout3(parse(source))[0].bands.map(b => b.items.filter(i => i.kind === "run").map(i => i.cells.join("")));

describe("flow large columns and balance small groups", () => {
  it("formats compact page 382 exactly as the requested standard and is idempotent", () => {
    expect(formatGj(compact)).toBe(standard);
    expect(formatGj(standard)).toBe(standard);
    expect(geometry(compact)).toEqual(geometry(standard));
    const page = layout3(parse(compact))[0];
    expect(page.bands.map(b => b.rows)).toEqual(Array(8).fill(24));
    expect(page.diagnostics).toEqual([]);
    expect(runs(compact)[4].slice(-2)).toEqual(["集", "韻"]);
    expect(runs(compact)[5].slice(0, 2)).toEqual(["同", "襄"]);
  });
  it("ignores physical folds and blank lines, counts * slots and Unicode codepoints", () => {
    const a = "@1\n𠀀甲*乙丙\n#丁\n戊己庚辛壬";
    const b = "@1\n\n𠀀\n甲*\n\n乙\n丙\n\n#丁\n\n戊己\n庚辛\n壬";
    expect(geometry(a)).toEqual(geometry(b));
    expect(runs(a)).toEqual([["𠀀甲 ", "乙丙", "戊己庚", "辛壬"]]);
    expect(formatGj(a)).toBe(formatGj(b));
  });
  it.each([
    ["甲乙。\n《書》丙", "甲乙。\n《書》丙"],
    ["《甲乙》。\n《丙丁》", "《甲乙》。\n《丙丁》"],
    ["甲𠀀。《\n【書】》乙", "甲𠀀。\n《【書】》乙"],
    ["甲".repeat(48) + "。《書》丙", "甲".repeat(24) + "\n" + "甲".repeat(24) + "。\n\n《書》\n丙"],
  ])("keeps opening book punctuation with the following cell across automatic folds: %s", (text, expected) => {
    const source = `@1\n${text}`;
    const formatted = formatGj(source);
    expect(formatted).toBe(`@1\n\n${expected}\n`);
    expect(geometry(formatted)).toEqual(geometry(source));
    expect(formatGj(formatted)).toBe(formatted);
    const doc = parse(source);
    expect(visibleLayout(flowDocument(doc))).toEqual(visibleLayout(doc));
    const index = buildCharIndex(doc);
    expect(index.map(e => e.src)).toEqual(index.map(e => e.src).sort((a, b) => a - b));
    for (const e of index) {
      const ch = String.fromCodePoint(source.codePointAt(e.src)!);
      expect(charHighlightAt(index, source, e.src + ch.length)).toEqual(e.target);
    }
  });
  it("places a one-character ordinary group in the front small column", () => {
    const page = layout3(parse("@1\n甲\n#乙"))[0];
    const first = page.bands[0].items.find(i => i.kind === "run" && i.cells.length)!;
    expect(first).toMatchObject({ cells: ["甲"], c: 1, halfShift: undefined });
    expect(formatGj("@1\n甲$\n乙")).toBe("@1\n\n甲$\n\n乙\n");
  });
  it("fills residual space before flowing to the next big column", () => {
    const source = `@1\n#${"甲".repeat(11)}\n乙丙丁戊己庚`;
    expect(runs(source)).toEqual([["乙丙", "丁戊"], ["己", "庚"]]);
    expect(layout3(parse(source))[0].bands.map(b => b.rows)).toEqual([24, 1]);
    expect(formatGj(source)).toBe(`@1\n\n#${"甲".repeat(11)}\n乙丙\n丁戊\n\n己\n庚\n`);
  });
  it("retains the centered guwen marker across cosmetic and automatic column boundaries", () => {
    const source = `@1\n${"甲".repeat(46)}\n#乙\n古\n\n文：\n#丙`;
    expect(geometry(source)).toEqual(geometry(source.replace("古\n\n文", "古文")));
    const doc = parse("@1\n#甲\n古文：\n#乙");
    expect(layout3(doc)[0].bands[0].items.find(i => i.kind === "run")).toMatchObject({ cells: ["古", "文"], halfShift: 0.5 });
  });
  it.each(["$", "¥"])("uses line-ending %s for a forced big-column break", marker => {
    const source = `@312\n#康熙字典${marker}\n#*子集上${marker}\n#**一部${marker}\n#一\n甲乙丙丁戊${marker}\n己庚`;
    const doc = parse(source);
    expect(doc.pages[0].bands).toHaveLength(5);
    expect(doc.pages[0].bands.slice(0, 4).every(b => b.breakAfter)).toBe(true);
    expect(runs(source).slice(3)).toEqual([["甲乙丙", "丁戊"], ["己", "庚"]]);
    expect(formatGj(source)).toBe("@312\n\n#康熙字典$\n\n#*子集上$\n\n#**一部$\n\n#一\n甲乙丙\n丁戊$\n\n己\n庚\n");
    expect(irToText(doc)).not.toMatch(/[$¥]/);
  });
  it("does not add an empty column after a full column or consecutive breaks", () => {
    const source = `@1\n#${"甲".repeat(12)}$\n$\n乙丙`;
    expect(parse(source).pages[0].bands).toHaveLength(2);
    expect(formatGj(formatGj(source))).toBe(formatGj(source));
    expect(layout3(parse(`@1\n${"甲".repeat(385)}`))[0].diagnostics.map(d => d.code)).toEqual(["band-count", "page-width"]);
  });
  it("does not turn cosmetic whitespace before a break into an empty slot", () => {
    for (const marker of ["$", "¥"]) {
      const source = `@1\n甲乙 ${marker} // 注\n丙丁`;
      const formatted = formatDocument(source).text;
      expect(geometry(formatted)).toEqual(geometry(source));
      expect(formatDocument(formatted).text).toBe(formatted);
      expect(formatted).toMatch(/乙\$ ?\/\/ 注/);
    }
  });
  it("recognizes only a trailing marker, including before comments", () => {
    expect(runs("@1\n甲$乙¥丙")).toEqual([["甲$乙", "¥丙"]]);
    expect(parse("@1\n甲乙$ // 注\n丙丁").pages[0].bands).toHaveLength(2);
    expect(nextGujiToken("甲¥", 1)).toMatchObject({ tok: "keyword" });
  });
  it("treats orphan closing book brackets identically across cosmetic folds", () => {
    const a = "@1\n甲乙丙】丁";
    expect(geometry("@1\n甲\n\n乙\n丙】丁")).toEqual(geometry(a));
    expect(formatGj(a)).toBe(formatGj("@1\n甲\n乙丙】丁"));
  });
  it("reflows with explicit per-page layout, retaining forced breaks through JSON", () => {
    const book = structuredClone(KANGXI_DATASET.layout);
    book.pages = { "2": { ...book.default, id: "short", spec: { ...book.default.spec, largeCellsPerBand: 1 } } };
    const source = "@1\n#甲$\n乙丙丁戊己庚\n@2\n#甲$\n乙丙丁戊己庚";
    const doc = applyBookLayout(gj2ir(source), book);
    expect(doc.pages.map(p => p.bands.length)).toEqual([2, 3]);
    expect(formatGj(source, book)).toBe("@1\n\n#甲$\n\n乙丙丁\n戊己庚\n\n@2\n\n#甲$\n\n乙丙\n丁戊\n\n己\n庚\n");
    expect(visibleLayout(applyBookLayout(JSON.parse(JSON.stringify(doc)), KANGXI_DATASET.layout))).toEqual(geometry(source));
    expect(visibleLayout(flowDocument(doc))).toEqual(visibleLayout(doc));
  });
});

describe("formatting, decoration and original source linkage", () => {
  it.each([
    "@1\n#甲 // 注\n#乙$ // 尾\n丙丁",
    "// 页注\n@1\n#甲\n// 中注\n#乙\n丙丁\n// 尾注",
    "@1\n甲乙 // 释文\n丙丁戊\n#己",
    "@1\n【\n甲\n\n乙】\n#(15)𠀀\n【史\n@2\n記】丙",
    "@1\n甲  乙　丙\n#丁 戊",
    "@1\n甲\n乙\n丙\n丁\n戊",
    "@1\n甲$乙¥丙",
    "@1\n甲$乙丙",
    "@1\n#甲\n#乙\n丙丁",
    "@1\n#甲\n\n，乙丙丁",
    "// 只有注释",
    "@1\n// 空页注释",
    "@1\n甲乙\n// 下一页\n@2\n丙丁",
  ])("preserves content, geometry, books and comments: %s", source => {
    const formatted = formatGj(source);
    expect(geometry(formatted)).toEqual(geometry(source));
    expect(formatGj(formatted)).toBe(formatted);
    expect(kangxiEntries(formatted).map(e => e.head)).toEqual(kangxiEntries(source).map(e => e.head));
    for (const comment of source.match(/\/\/[^\n]*/g) ?? []) expect(formatted).toContain(comment);
  });
  it("keeps every glyph mapped to the compact source, including circles and astral text", () => {
    const source = compact;
    const doc = parse(source), index = buildCharIndex(doc);
    expect(index.map(e => e.src)).toEqual(index.map(e => e.src).sort((a, b) => a - b));
    for (const e of index) {
      const ch = String.fromCodePoint(source.codePointAt(e.src)!);
      expect(charHighlightAt(index, source, e.src + ch.length)).toEqual(e.target);
    }
    for (const band of doc.pages[0].bands) {
      const target = bandCursorTarget(doc, source, 382, band.ord)!;
      expect(target).toBeGreaterThan(0);
      const hit = charHighlightAt(index, source, target)!;
      expect(band.lines.some(l => hit.kind === "cell" ? l.id === hit.lineId : l.elements.some(e => e.id === hit.elId))).toBe(true);
    }
    const noSource = JSON.parse(JSON.stringify(doc), (k, v) => k === "src" || k === "cpSrcs" ? undefined : v);
    expect(visibleLayout(noSource)).toEqual(visibleLayout(doc));
    expect(visibleLayout(flowDocument(noSource))).toEqual(visibleLayout(doc));
  });
});
