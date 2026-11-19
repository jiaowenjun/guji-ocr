// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ScanGridLines, ScanGridOverlay } from "../src/components/dataset/ScanGridOverlay";
import { assertScanGridLayout, compareBlankCells, type ScanGrid } from "../src/components/dataset/scan-grid";
import { useScanGrid } from "../src/components/dataset/use-scan-grid";
import { MatrixPages } from "../src/components/matrix/MatrixPages";
import { layout3, type L3Page } from "../src/ir/layout3";
import { foldedDocument } from "./helpers/folded-document";
import type { PageEntry } from "../src/components/dataset/DatasetView";

const laid = (source: string) => layout3(foldedDocument(source))[0];
const grid: ScanGrid = { width: 1130, height: 1679,
  bands: Array.from({ length: 8 }, (_, i) => [1000 - (i + 1) * 120, 168 + i, 1000 - i * 120, 1564 + i]),
  blank_cells: [],
};

it("只验证原图支持的版式，不依赖草稿占格", () => {
  const page = laid("@312\n\n#(十一)\n甲*乙\n丙*丁\n\n#*戊\n");
  expect(() => assertScanGridLayout(page)).not.toThrow();
  expect(() => assertScanGridLayout(laid("@312\n"))).not.toThrow();
  expect(() => assertScanGridLayout({ ...page, config: { ...page.config, rowCap: 20 } })).toThrow("8×12");
});

it("按物理小格双向对照：都空为蓝，只有一侧空为红，都有字不着色", () => {
  const page = laid("@312\n\n#甲\n乙*丙\n丁戊*\n");
  const highlights = compareBlankCells(page, { ...grid, blank_cells: [
    { band: 0, col: 1, row: 3 }, { band: 7, col: 0, row: 23 },
    { band: 0, col: 1, row: 2 }, // 原图空、渲染有字，也需要红色提示。
    { band: 0, col: 1, row: 0 }, // 大字占位不拆分为小空格。
  ] });
  expect(highlights).toContainEqual({ col: 15, row: 3, match: true });
  expect(highlights).toContainEqual({ col: 14, row: 4, match: false });
  expect(highlights).toContainEqual({ col: 0, row: 23, match: true });
  expect(highlights.some(c => c.col >= 14 && c.row < 2)).toBe(false);
  expect(highlights).toContainEqual({ col: 15, row: 2, match: false });
  expect(highlights.some(c => c.col === 15 && c.row === 4)).toBe(false);
  expect(highlights).toHaveLength(384 - 4 - 4 + 1);

  const container = document.createElement("div");
  container.innerHTML = renderToStaticMarkup(createElement(MatrixPages, {
    pages: [page], cells: true, blankCells: new Map([[page, highlights]]),
  }));
  const match = container.querySelector<HTMLElement>('[data-render-blank="15:3"]')!;
  expect(match.dataset.blankMatch).toBe("yes");
  expect(match.classList.contains("m-blank-cell-match")).toBe(true);
  expect(match.style.gridColumn).toBe("16 / 17");
  expect(match.style.gridRow).toBe("4 / 5");
  expect(container.querySelector('[data-render-blank="14:4"]')?.classList.contains("m-blank-cell-mismatch")).toBe(true);
  expect(container.querySelector('[data-render-blank="15:2"]')?.classList.contains("m-blank-cell-mismatch")).toBe(true);
  expect([...container.querySelectorAll(".m-cell")].some(c => c.textContent === "乙")).toBe(true);
  container.innerHTML = renderToStaticMarkup(createElement(MatrixPages, {
    pages: [page], cells: false, blankCells: new Map([[page, highlights]]),
  }));
  expect(container.querySelector(".m-lines")?.getAttribute("data-cells")).toBe("off");
  expect(container.querySelectorAll("[data-render-blank]")).toHaveLength(highlights.length);
  container.innerHTML = renderToStaticMarkup(createElement(MatrixPages, { pages: [page], cells: false }));
  expect(container.querySelector("[data-render-blank]")).toBeNull();
});

it("大字空位不拆分，半格居中的小字和版框外内容不会被错判为空格", () => {
  const largeBlank = compareBlankCells(laid("@312\n\n#*\n"), grid);
  expect(largeBlank).toHaveLength(380);
  expect(largeBlank.some(c => c.col >= 14 && c.row < 2)).toBe(false);
  const centered = compareBlankCells(laid("@312\n\n古文\n"), grid);
  expect(centered.some(c => c.col >= 14 && c.row < 2)).toBe(false);
  const overflow = laid(`@312\n\n${Array(8).fill("#甲").join("\n\n")}\n\n${"乙".repeat(25)}\n`);
  expect(compareBlankCells(overflow, grid)).toHaveLength(384 - 8 * 4);
  const halfBand = laid(`@312\n\n${Array(7).fill("#甲").join("\n\n")}\n\n乙*\n丁戊\n己庚\n`);
  const compared = compareBlankCells(halfBand, { ...grid, blank_cells: [{ band: 7, col: 1, row: 1 }] });
  expect(compared).toContainEqual({ col: 1, row: 1, match: true });
  expect(compared.some(c => c.col === 0 && c.row === 1)).toBe(false);
});

it("原图裁切和缺失的列不误报为红色不匹配", () => {
  const clipped: ScanGrid = { ...grid, bands: grid.bands.map((b, i) => i === 7 ? [-60, 168, 60, 1564] : b) };
  const result = compareBlankCells(laid("@312\n"), clipped);
  expect(result.filter(c => c.col === 0)).toHaveLength(0);
  expect(result.filter(c => c.col === 1)).toHaveLength(24);
  expect(compareBlankCells(laid("@312\n"), { ...grid, bands: [] })).toEqual([]);
});

it("只高亮图像识别出的空格，使用所属大列的小格坐标", () => {
  const container = document.createElement("div");
  const detected = { ...grid, blank_cells: [{ band: 0, col: 1, row: 7 }, { band: 7, col: 0, row: 23 }] };
  container.innerHTML = renderToStaticMarkup(createElement(ScanGridLines, {
    grid: detected,
  }));
  const blanks = [...container.querySelectorAll<HTMLElement>("[data-scan-blank]")];
  expect(blanks).toHaveLength(2);
  expect(blanks.map((cell) => cell.parentElement?.dataset.scanBand)).toEqual(["0", "7"]);
  expect(blanks.map((cell) => cell.style.left)).toEqual(["50%", "0%"]);
  expect(parseFloat(blanks[0].style.top)).toBeCloseTo(7 / 24 * 100, 3);
  expect(parseFloat(blanks[1].style.top)).toBeCloseTo(23 / 24 * 100, 3);
  expect(blanks[0].style.width).toBe("50%");
  expect(parseFloat(blanks[0].style.height)).toBeCloseTo(100 / 24, 3);
  expect(container.querySelectorAll(".scan-cell-rule")).toHaveLength(8 * 28);
  container.innerHTML = renderToStaticMarkup(createElement(ScanGridLines, { grid: detected, cells: false }));
  expect(container.querySelectorAll("[data-scan-blank]")).toHaveLength(2);
  expect(container.querySelector(".scan-cell-rule")).toBeNull();
});

it("每列都画满 12 个大格和 24 行小格，按各列独立起点投影", () => {
  const container = document.createElement("div");
  container.innerHTML = renderToStaticMarkup(createElement(ScanGridLines, { grid }));
  const bands = [...container.querySelectorAll<HTMLElement>("[data-scan-band]")];
  expect(bands).toHaveLength(8);
  for (const [i, band] of bands.entries()) {
    expect(parseFloat(band.style.top)).toBeCloseTo((168 + i) / 1679 * 100, 3);
    expect(band.querySelectorAll(".scan-cell-rule-v")).toHaveLength(3);
    const rows = [...band.querySelectorAll<HTMLElement>(".scan-cell-rule-h")];
    expect(rows).toHaveLength(25);
    expect(rows[0].style.top).toBe("0%");
    expect(rows[24].style.top).toBe("100%");
    expect(rows.filter((row) => row.classList.contains("scan-cell-rule-minor"))).toHaveLength(12);
  }
});

let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.useFakeTimers();
  container = document.createElement("div");
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function Overlay({ entry, layout, enabled }: { entry: PageEntry; layout: L3Page; enabled: boolean }) {
  const state = useScanGrid(entry, layout, enabled);
  return enabled ? createElement(ScanGridOverlay, { state }) : null;
}
function show(page: number, source = `@${page}\n#甲\n`, enabled = true) {
  const entry: PageEntry = { page, image: `${page}.jpg`, gj: `${page}.gj`, width: 1130, height: 1679 };
  return act(async () => root.render(createElement(Overlay, { entry, layout: laid(source), enabled })));
}
const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(250); });

it("切页取消旧请求，晚到响应不会覆盖新页；关闭时取消计算", async () => {
  const pending: { signal: AbortSignal; resolve: (value: unknown) => void }[] = [];
  vi.stubGlobal("fetch", vi.fn((_url, init) => new Promise((resolve) => pending.push({ signal: init.signal, resolve }))));
  await show(313);
  await flush();
  await show(314);
  expect(pending[0].signal.aborted).toBe(true);
  await flush();
  await act(async () => pending[0].resolve({ ok: true, json: async () => ({ ok: true, ...grid }) }));
  expect(container.querySelector("[data-scan-grid]")).toBeNull();
  await act(async () => pending[1].resolve({ ok: true, json: async () => ({ ok: true, ...grid }) }));
  expect(container.querySelectorAll("[data-scan-band]")).toHaveLength(8);
  await show(315);
  expect(container.querySelector("[data-scan-grid]")).toBeNull();
  await flush();
  await show(315, "@315\n#甲\n", false);
  expect(pending[2].signal.aborted).toBe(true);
});

it("换字、补空格和大字重排都复用同一原图结果，请求不含草稿先验", async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ ok: true, ...grid }) }));
  vi.stubGlobal("fetch", fetcher);
  await show(316);
  await flush();
  await show(316, "@316\n#乙\n");
  await flush();
  await show(316, "@316\n*又使也\n#甲乙\n");
  await flush();
  await show(316, "@316\n");
  await flush();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(JSON.parse((fetcher.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)).toEqual({ page: 316 });
  expect(container.querySelectorAll("[data-scan-band]")).toHaveLength(8);
});

it("原图识别失败可重试", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: false, json: async () => ({ ok: false, error: "定位失败" }) })
    .mockResolvedValue({ ok: true, json: async () => ({ ok: true, ...grid }) });
  vi.stubGlobal("fetch", fetcher);
  await show(317);
  expect(container.querySelector("[data-scan-grid]")).toBeNull();
  await flush();
  expect(container.textContent).toContain("定位失败");
  await act(async () => container.querySelector("button")!.click());
  await flush();
  expect(container.querySelectorAll("[data-scan-band]")).toHaveLength(8);
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("编辑草稿不会取消进行中的原图检测", async () => {
  let finish!: (value: unknown) => void;
  const fetcher = vi.fn((_url, init) => new Promise(resolve => { finish = resolve; expect(init.signal.aborted).toBe(false); }));
  vi.stubGlobal("fetch", fetcher);
  await show(318);
  await flush();
  await show(318, "@318\n*又使也\n#甲\n");
  await flush();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(false);
  await act(async () => finish({ ok: true, json: async () => ({ ok: true, ...grid }) }));
  expect(container.querySelectorAll("[data-scan-band]")).toHaveLength(8);
});
