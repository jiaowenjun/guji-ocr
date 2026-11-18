// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ScanGridLines, ScanGridOverlay } from "../src/components/dataset/ScanGridOverlay";
import { scanGridPrior, type ScanGrid } from "../src/components/dataset/scan-grid";
import { layout3 } from "../src/ir/layout3";
import { foldedDocument } from "./helpers/folded-document";
import type { PageEntry } from "../src/components/dataset/DatasetView";

const laid = (source: string) => layout3(foldedDocument(source))[0];
const grid: ScanGrid = { width: 1130, height: 1679,
  bands: Array.from({ length: 8 }, (_, i) => [1000 - (i + 1) * 120, 168 + i, 1000 - i * 120, 1564 + i]),
  blank_cells: [],
};

it("拟合先验保留空格行位、合字完整跨度，并补足八列", () => {
  const spans = scanGridPrior(laid("@312\n\n#(十一)\n甲*乙\n丙*丁\n\n#*戊\n"));
  expect(spans).toHaveLength(8);
  expect(spans[0]).toEqual([[0, 2], [2, 3], [4, 5]]);
  expect(spans[1]).toEqual([[2, 4]]);
  expect(spans.slice(2)).toEqual(Array.from({ length: 6 }, () => []));
  expect(scanGridPrior(laid("@312\n"))).toEqual(Array.from({ length: 8 }, () => []));
});

it("只高亮图像识别出的空格，使用所属大列的小格坐标", () => {
  const container = document.createElement("div");
  container.innerHTML = renderToStaticMarkup(createElement(ScanGridLines, {
    grid: { ...grid, blank_cells: [{ band: 0, col: 1, row: 7 }, { band: 7, col: 0, row: 23 }] },
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

function show(page: number, source = `@${page}\n#甲\n`) {
  const entry: PageEntry = { page, image: `${page}.jpg`, gj: `${page}.gj`, width: 1130, height: 1679 };
  return act(async () => root.render(createElement(ScanGridOverlay, { entry, layout: laid(source) })));
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
  await act(async () => root.render(null));
  expect(pending[2].signal.aborted).toBe(true);
});

it("编辑占格后重新拟合，同占格换字复用结果，失败可重试", async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ ok: true, ...grid }) }));
  vi.stubGlobal("fetch", fetcher);
  await show(316);
  await flush();
  await show(316, "@316\n#乙\n");
  await flush();
  expect(fetcher).toHaveBeenCalledTimes(1);
  fetcher.mockResolvedValueOnce({ ok: false, json: async () => ({ ok: false, error: "定位失败" }) } as never);
  await show(316, "@316\n#甲乙\n");
  expect(container.querySelector("[data-scan-grid]")).toBeNull();
  await flush();
  expect(container.textContent).toContain("定位失败");
  await act(async () => container.querySelector("button")!.click());
  await flush();
  expect(container.querySelectorAll("[data-scan-band]")).toHaveLength(8);
  expect(fetcher).toHaveBeenCalledTimes(3);
});
