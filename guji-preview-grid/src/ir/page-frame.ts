import type { L3Page } from "./layout3";

/** 显示版框与内容包围盒分开：缺列留在左侧，短列留满版高。
 *  异常超宽页仍完整展示并沿用版式诊断，不裁掉待校对的内容。 */
export function getPageFrame(page: L3Page) {
  const { expectedBands, smallColumnsPerBand, rowCap } = page.config;
  const cols = Math.max(page.totalCols, (expectedBands ?? 0) * smallColumnsPerBand);
  return { cols, rows: rowCap, colOffset: cols - page.totalCols };
}
