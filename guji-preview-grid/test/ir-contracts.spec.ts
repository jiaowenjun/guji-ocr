import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, it, expect } from "vitest";
import { gj2ir } from "../src/ir/gj2ir";
import { irPageToText, irToText } from "../src/ir/text";
import { layout3, planLayoutBand } from "../src/ir/layout3";
import { KANGXI_LAYOUT } from "../src/ir/layout-config";
import { diagnoseLayout } from "../src/ir/layout-diagnostics";
import { indexLayout, projectBooks, locateCell } from "../src/ir/projection";
import { compileProfile } from "../src/ir/profile";
import { parsePages } from "../src/parser/parse-pages";
import { formatDocument } from "../src/components/dataset/format-document";
import { nextGujiToken } from "../src/components/editor/guji-language";
import { MatrixPages } from "../src/components/matrix/MatrixPages";
import type { IRBookOverlay } from "../src/ir/types";
const root = new URL("../../", import.meta.url);
const read = (path: string) => readFileSync(new URL(path, root), "utf8");

describe("document profile and provenance", () => {
  it("shares ordered normalization with layout, TXT and Python, including repeated patterns", () => {
    const doc = gj2ir("@1\n\n𠀀甲，乙甲\n");
    doc.meta.profile = { stripPunct: ["，"], normalize: [["𠀀甲", "丁"], ["乙", "甲"], ["甲", "戊己"], ["戊己", "庚"]] };
    const run = layout3(doc)[0].bands[0].items[0];
    expect(run.cells).toEqual(["丁", "庚", "庚"]);
    expect(run.rawRanges).toEqual([[0, 2], [3, 4], [4, 5]]);
    expect(irToText(doc)).toBe("丁庚庚\n");
    expect(irPageToText(doc.pages[0], doc.meta.profile)).toBe(irToText(doc));
    const py = `import sys,runpy,tempfile\nfrom pathlib import Path\nfn=runpy.run_path(sys.argv[1])['ir_reference']\nwith tempfile.TemporaryDirectory() as d:\n p=Path(d)/'doc.json'\n p.write_text(sys.stdin.read())\n sys.stdout.write(fn(p))`;
    expect(execFileSync("python3", ["-I", "-c", py, fileURLToPath(new URL("kangxi-gold/scripts/eval_cer.py", root))], { input: JSON.stringify(doc), encoding: "utf8" })).toBe(irToText(doc));
    doc.meta.profile.normalize = [["甲", "乙"], ["甲", "丙"]];
    expect(execFileSync("python3", ["-I", "-c", py, fileURLToPath(new URL("kangxi-gold/scripts/eval_cer.py", root))], { input: JSON.stringify(doc), encoding: "utf8" })).toBe(irToText(doc));
  });
  it("normalizes displayed large glyphs and headings, preserving skeleton text", () => {
    const doc = gj2ir("@1\n\n# 〇\n\n#〇\n");
    const before = JSON.stringify(doc.pages);
    expect(layout3(doc).flatMap((p) => p.bands.flatMap((b) => b.items.map((i) => i.text)))).toEqual(["○", "○"]);
    expect(JSON.stringify(doc.pages)).toBe(before);
    expect(irToText(doc)).toBe("○\n○\n");
  });
  it("maps expansions/deletions and rejects ambiguous profile rules", () => {
    const clean = compileProfile({ stripPunct: ["，"], normalize: [["甲", "乙丙"], ["丁", ""]] });
    expect(clean("甲，丁𠀀")).toEqual({ cells: ["乙", "丙", "𠀀"], ranges: [[0, 1], [0, 1], [3, 4]] });
    expect(() => compileProfile({ stripPunct: [], normalize: [["", "甲"]] })).toThrow();
    expect(() => compileProfile({ stripPunct: ["甲乙"], normalize: [] })).toThrow();
  });
  it("isolates profiles between parsed documents", () => {
    const a = gj2ir("@1\n\n甲，乙\n");
    a.meta.profile.stripPunct.length = 0;
    expect(irToText(a)).toBe("甲，乙\n");
    expect(irToText(gj2ir("@1\n\n甲，乙\n"))).toBe("甲乙\n");
  });
});

describe("layout plan and configuration", () => {
  it("plans small parallel runs separated by a glyph", () => {
    const doc = gj2ir("@1\n\n甲\n乙\n#丙\n丁\n");
    expect(planLayoutBand(doc.pages[0].bands[0], doc.meta.profile).segments.map((s) => s.kind)).toEqual(["parallel", "glyph", "parallel"]);
    expect(layout3(doc)[0].bands[0].rows).toBe(4);
  });
  it("uses configured glyph size and clipping cap in the rendered grid", () => {
    const doc = gj2ir("@1\n\n#甲\n乙丙丁\n");
    doc.meta.layout = { ...KANGXI_LAYOUT, rowCap: 4, expectedBands: null, largeRows: 3, largeCols: 3, smallColumnsPerBand: 3 };
    const pages = layout3(doc);
    expect(pages[0].bands[0]).toMatchObject({ cols: 3, rows: 6 });
    expect(pages[0].diagnostics.map((d) => d.code)).toEqual(["overflow"]);
    const markup = renderToStaticMarkup(createElement(MatrixPages, { pages }));
    expect(markup).toContain("repeat(4,");
    expect(markup).toContain("grid-row:1 / span 3;grid-column:1 / span 3");
    expect(markup).toContain("底部 2 格已隐藏");
    doc.meta.layout.rowCap = 0;
    expect(() => layout3(doc)).toThrow("rowCap");
  });
  it("detects overlaps of centered half-cell runs", () => {
    const page = layout3(gj2ir("@1\n\n甲乙\n"))[0];
    page.bands[0].items.push({ ...page.bands[0].items[0] });
    expect(diagnoseLayout(page).some((d) => d.code === "overlap" && d.severity === "error")).toBe(true);
  });
  it("diagnoses a three-column group without changing its contents", () => {
    const doc = gj2ir("@1\n\n甲\n乙\n丙\n");
    const page = layout3(doc)[0];
    expect(page.diagnostics.map((d) => d.code)).toEqual(["band-count", "page-width", "band-width"]);
    expect(page.totalCols).toBe(3);
    expect(irToText(doc)).toBe("甲乙丙\n");
  });
  it("keeps explicit empty columns through parsing, formatting and highlighting", () => {
    const source = "@1\n\n@blank\n\n甲乙\n";
    const a = gj2ir(source);
    const b = gj2ir(source.replace("@blank", "#"));
    expect(layout3(a)).toEqual(layout3(b));
    expect(irToText(a)).toBe("\n甲乙\n");
    expect(parsePages(source)).toEqual(parsePages(source.replace("@blank", "#")));
    expect(formatDocument(source).text).toBe(source);
    expect(nextGujiToken("@blank", 0, true)).toMatchObject({ tok: "keyword", inBookAfter: true });
    expect(layout3(a)[0].diagnostics.filter((d) => d.code === "empty-band")).toHaveLength(1);
    expect(irToText(gj2ir("@1\n\n正文@blank\n"))).toContain("正文@blank");
  });
});

describe("overlay projection", () => {
  it("opens cross-page seams with opaque IDs and partial page rendering", () => {
    const doc = gj2ir("@1\n\n【史\n\n@2\n\n記】文\n");
    const book = doc.overlays.find((o): o is IRBookOverlay => o.kind === "book-title")!;
    expect(book.spans).toHaveLength(2);
    doc.pages.forEach((p, i) => {
      p.bands[0].id = `opaque-band-${i}`;
      book.spans[i].line = p.bands[0].lines[0].id = `arbitrary-line-${i}`;
    });
    const pages = layout3(doc);
    const boxes = projectBooks(pages, doc.overlays);
    expect(boxes.get(pages[0])![0]).toMatchObject({ openTop: false, openBottom: true });
    expect(boxes.get(pages[1])![0]).toMatchObject({ openTop: true, openBottom: false });
    for (const page of pages) expect(projectBooks([page], doc.overlays).get(page)).toEqual(boxes.get(page));
    const markup = renderToStaticMarkup(createElement(MatrixPages, { pages, overlays: doc.overlays }));
    expect(markup).toContain("m-book open-bottom");
    expect(markup).toContain("m-book open-top");
  });
  it("splits boxes across runs in one line and highlights only the target run", () => {
    const doc = gj2ir("@1\n\n甲#乙：丙丁\n");
    const line = doc.pages[0].bands[0].lines[0];
    doc.overlays = [{ id: "book", kind: "book-title", spans: [{ line: line.id, range: [0, 5] }], openedHere: true, closed: true }];
    const pages = layout3(doc);
    const index = indexLayout(pages);
    const boxes = projectBooks(pages, doc.overlays, index).get(pages[0])!;
    expect(boxes.map((b) => [b.rowStart, b.rowEnd])).toEqual([[0, 1], [3, 5]]);
    expect(locateCell(index, line.id, 4)?.item.cells).toEqual(["丙", "丁"]);
    expect(locateCell(index, line.id, 4)?.index).toBe(1);
  });
  it("intersects contracted source ranges and skips punctuation-only frames", () => {
    const doc = gj2ir("@1\n\n甲乙\n，\n丙\n");
    doc.meta.profile.normalize = [["甲乙", "丁"]];
    const lines = doc.pages[0].bands[0].lines;
    doc.overlays = [{ id: "book", kind: "book-title", spans: [{ line: lines[0].id, range: [1, 2] }, { line: lines[1].id, range: [0, 1] }], openedHere: true, closed: true }];
    const pages = layout3(doc);
    expect(projectBooks(pages, doc.overlays).get(pages[0])).toMatchObject([{ rowStart: 0, rowEnd: 1, openTop: false, openBottom: false }]);
  });
});

it("preserves all 45 stored IR/TXT files and validates the corrected eight-band pages", () => {
  const manifest = JSON.parse(read("kangxi-gold/manifest.json"));
  const widthCandidates: number[] = [];
  for (const entry of manifest.pages) {
    const base = `kangxi-gold/annotations/${String(entry.page).padStart(4, "0")}`;
    const doc = gj2ir(read(`${base}.gj`));
    expect(doc, `IR @${entry.page}`).toEqual(JSON.parse(read(`${base}.json`)));
    expect(irToText(doc), `TXT @${entry.page}`).toBe(read(`${base}.txt`));
    const page = layout3(doc)[0];
    expect(page.bands).toHaveLength(8);
    expect(page.totalCols).toBe(16);
    if ([318, 320, 322, 325, 327].includes(entry.page))
      expect(page.bands.map((band) => band.rows)).toEqual(Array(8).fill(24));
    if (page.diagnostics.some((d) => d.code === "page-width")) widthCandidates.push(entry.page);
    expect(page.diagnostics.filter((d) => d.code === "overlap" || d.code === "overflow")).toEqual([]);
  }
  expect(widthCandidates).toEqual([]);
});
