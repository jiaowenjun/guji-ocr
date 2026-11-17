// @vitest-environment jsdom
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MatrixPages } from "../src/components/matrix/MatrixPages";
import { gj2ir } from "../src/ir/gj2ir";
import { applyBookLayout } from "../src/ir/document-layout";
import { compileBookLayout, resolveLayoutConfig, resolvePageLayout, type BookLayout, type BookLayoutSpec } from "../src/ir/layout-config";
import { layout3 } from "../src/ir/layout3";
import { getPageFrame } from "../src/ir/page-frame";
import { projectBooks, indexLayout, locateCell } from "../src/ir/projection";
import { irToText } from "../src/ir/text";
import { resolveDatasetConfig, resolvePageScan } from "../src/datasets/config";
import { KANGXI_DATASET, KANGXI_LAYOUT, importLegacyKangxiDocument, resolveDatasetIndexConfig } from "../src/datasets/kangxi";

const spec: BookLayoutSpec = { schemaVersion: 1, bandsPerPage: 8, largeCellsPerBand: 12, smallRowsPerLargeCell: 1 };
const equalHeight: BookLayout = { default: { id: "test-equal-height", revision: 1, spec } };

function render(book: BookLayout, source: string, cells = true) {
  const doc = applyBookLayout(gj2ir(source), book);
  const pages = layout3(doc);
  const root = document.createElement("div");
  root.innerHTML = renderToStaticMarkup(createElement(MatrixPages, { pages, overlays: doc.overlays, cells }));
  return { doc, pages, root };
}

describe("书籍版式与通用结构", () => {
  it.each([1, 2])("高度比 1:%i 派生固定页框、双小列和大字占格", (n) => {
    const config = compileBookLayout({ ...spec, smallRowsPerLargeCell: n });
    expect(config).toEqual({ version: 1, expectedBands: 8, rowCap: 12*n, smallColumnsPerBand: 2, largeCols: 2, largeRows: n });
    const { doc, pages, root } = render({ default: { ...equalHeight.default, spec: { ...spec, smallRowsPerLargeCell: n } } }, "@1\n\n#甲\n【乙丙】\n丁戊\n");
    expect(getPageFrame(pages[0])).toEqual({ cols: 16, rows: 12*n, colOffset: 14 });
    expect(pages[0].bands[0].items.map(i => i.r)).toEqual([0, n, n]);
    expect(projectBooks(pages, doc.overlays).get(pages[0])![0]).toMatchObject({ rowStart: n, rowEnd: n+2 });
    const run = pages[0].bands[0].items[1];
    expect(locateCell(indexLayout(pages), run.lineId!, 1)?.index).toBe(1);
    expect(root.querySelector<HTMLElement>(".m-large")!.style.gridRow).toBe(`1 / span ${n}`);
    expect(root.querySelectorAll(".m-cell-rule-v.m-cell-rule-minor")).toHaveLength(8);
    expect(root.querySelectorAll(".m-cell-rule-h:not(.m-cell-rule-minor)")).toHaveLength(11);
    expect(root.querySelectorAll(".m-cell-rule-h.m-cell-rule-minor")).toHaveLength(n === 1 ? 0 : 12);
    expect(root.querySelector<HTMLElement>(".m-lines")!.style.getPropertyValue("--guji-default-unit-v")).toBe(`calc(var(--guji-unit) * 2 / ${n})`);
  });

  it("不同页宽/高度与空页补齐由书籍决定，开关不改变内容或几何", () => {
    const book = { default: { ...equalHeight.default, spec: { ...spec, bandsPerPage: 10, largeCellsPerBand: 15 } } };
    for (const source of ["@1\n", "@1\n\n#甲\n乙\n丙\n"]) {
      const on = render(book, source), off = render(book, source, false);
      expect(getPageFrame(on.pages[0])).toMatchObject({ cols: 20, rows: 15 });
      expect(on.root.innerHTML).toBe(off.root.innerHTML.replace('data-cells="off"', 'data-cells="on"'));
    }
  });

  it("同书不同页使用各自快照，跨页书名延续；预设后续修改不改变旧 IR", () => {
    const book = structuredClone(KANGXI_DATASET.layout);
    book.pages = { "2": equalHeight.default };
    const doc = applyBookLayout(gj2ir("@1\n\n#甲\n【史\n\n@2\n\n記】文\n"), book);
    const saved = JSON.parse(JSON.stringify(doc));
    book.default.spec.largeCellsPerBand = 99;
    const pages = layout3(saved);
    expect(pages.map(p => getPageFrame(p).rows)).toEqual([24, 12]);
    expect(saved.meta.layoutPreset).toEqual({ id: "kangxi-wuyingdian", revision: 1 });
    expect(saved.pages[1].layoutPreset).toEqual({ id: "test-equal-height", revision: 1 });
    expect(saved.pages[0].layout).toBeUndefined();
    expect(resolvePageLayout(book, 2).config.rowCap).toBe(12);
    const boxes = projectBooks(pages, doc.overlays);
    expect(boxes.get(pages[0])![0]).toMatchObject({ rowStart: 2, openBottom: true });
    expect(boxes.get(pages[1])![0]).toMatchObject({ rowStart: 0, openTop: true });
    expect(applyBookLayout(doc, equalHeight).pages[1].layout).toBeUndefined();
    expect(irToText(saved)).toBe(irToText(doc));
  });

  it("纯解析不猜书籍，旧康熙导入显式补齐且不改骨架", () => {
    const raw = gj2ir("@1\n\n#甲\n");
    expect(raw.meta.layout).toBeUndefined();
    expect(() => layout3(raw)).toThrow("Missing layout");
    const imported = importLegacyKangxiDocument(raw);
    expect(imported.meta.layout).toEqual(KANGXI_LAYOUT);
    expect(imported.pages).toEqual(raw.pages);
    const originalHeight = KANGXI_DATASET.layout.default.spec.smallRowsPerLargeCell;
    try {
      KANGXI_DATASET.layout.default.spec.smallRowsPerLargeCell = 1;
      expect(importLegacyKangxiDocument(raw).meta.layout?.rowCap).toBe(24);
    } finally {
      KANGXI_DATASET.layout.default.spec.smallRowsPerLargeCell = originalHeight;
    }
    expect(raw.meta.layout).toBeUndefined();
    expect(() => resolveDatasetIndexConfig(undefined, "another-book")).toThrow();
    expect(resolveDatasetIndexConfig(undefined, "kangxi-gold")).toEqual(KANGXI_DATASET);
  });

  it("历史 v1 自定义几何不被新规则覆盖，非法配置也不悄悄回退", () => {
    const raw = gj2ir("@1\n\n#甲\n\n@2\n\n#乙\n");
    raw.meta.layout = { version: 1, rowCap: 7, expectedBands: null, smallColumnsPerBand: 3, largeCols: 3, largeRows: 3 };
    raw.pages[1].layout = { ...KANGXI_LAYOUT, rowCap: 4 };
    const imported = importLegacyKangxiDocument(raw);
    expect(imported).toEqual(raw);
    expect(layout3(imported).map(p => getPageFrame(p))).toEqual([{ cols: 3, rows: 7, colOffset: 0 }, { cols: 16, rows: 4, colOffset: 14 }]);
    raw.meta.layout.version = 99 as 1;
    expect(() => importLegacyKangxiDocument(raw)).toThrow("Unsupported layout version");
    expect(() => resolveLayoutConfig(undefined)).toThrow("Missing layout");
  });

  it.each([0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER+1])("拒绝非法独立参数 %s", (n) => {
    for (const key of ["bandsPerPage", "largeCellsPerBand", "smallRowsPerLargeCell"] as const)
      expect(() => compileBookLayout({ ...spec, [key]: n })).toThrow("positive integer");
  });
  it("校验版本、预设标识和派生溢出", () => {
    expect(() => compileBookLayout({ ...spec, schemaVersion: 2 as 1 })).toThrow("version");
    expect(() => compileBookLayout({ ...spec, largeCellsPerBand: Number.MAX_SAFE_INTEGER, smallRowsPerLargeCell: 2 })).toThrow("rowCap");
    expect(() => resolvePageLayout({ default: { ...equalHeight.default, id: "" } }, 1)).toThrow("id");
  });

  it("扫描尺寸与版式正交，支持页级扫描参数且拒绝无效输入", () => {
    const config = resolveDatasetConfig(KANGXI_DATASET);
    config.scanPages = { "2": { margin: { left: 20, right: 20, top: 30, bottom: 30 }, background: "#ffffff" } };
    expect(resolvePageScan(config, 2)).toBe(config.scanPages["2"]);
    expect(resolvePageScan(config, 1)).toBe(config.scan);
    expect(config.layout).toEqual(KANGXI_DATASET.layout);
    config.scan.margin.left = -1;
    expect(() => resolveDatasetConfig(config)).toThrow("scan.margin.left");
    expect(KANGXI_DATASET.scan.margin.left).toBe(124);
  });
});
