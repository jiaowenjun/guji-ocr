import type { L3Page } from "./layout3";

/** 版框固定，正文靠右：缺列留白，超宽列向左溢出（负偏移）。
 *  只限制可见版框，不改动原始内容与布局坐标。 */
export function getPageFrame(page: L3Page) {
  const { expectedBands, smallColumnsPerBand, rowCap } = page.config;
  const cols = expectedBands === null ? page.totalCols : expectedBands * smallColumnsPerBand;
  return { cols, rows: rowCap, colOffset: cols - page.totalCols };
}
