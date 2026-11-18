import { getItemBounds } from "@/ir/layout-geometry";
import { getPageFrame } from "@/ir/page-frame";
import type { L3Page } from "@/ir/layout3";

export type RowSpan = [number, number];
export type ScanBandBox = [number, number, number, number];
export interface ScanGrid {
  width: number;
  height: number;
  /** 八个大列，从右到左；每列独立拟合纵向起点与行距。 */
  bands: ScanBandBox[];
  /** 原图墨迹识别的空白小格；col 从左到右，row 从上到下，均从 0 开始。 */
  blank_cells: Array<{ band: number; col: number; row: number }>;
}

/** 双向比较固定版框内的空格：两侧都空为匹配，仅一侧空为不匹配。
 *  坐标统一为页面左到右、上到下，两侧都有字的小格不高亮。
 *  大字（包括显式大字空位）不拆成四个空格；半格居中的墨字占用所有相交格。
 *  未排字区域同样参与比较，原图裁切或未成功定位的格子保留未知。 */
export function compareBlankCells(page: L3Page, scan: ScanGrid) {
  const { cols, rows, colOffset } = getPageFrame(page);
  if (cols !== 16 || rows !== 24 || page.config.largeCols !== 2 || page.config.largeRows !== 2) return [];
  const occupancy = Array.from({ length: cols }, () => Array<"blank" | "text" | "large">(rows).fill("blank"));
  page.bands.forEach((band, bi) => {
    for (const item of band.items) {
      const bounds = getItemBounds(item, page.config);
      const left = page.colStarts[bi] + colOffset + bounds.x;
      const texts = item.kind === "large" ? [item.text] : item.cells;
      texts.forEach((text, i) => {
        if (item.kind !== "large" && !text.trim()) return;
        const top = bounds.y + i;
        const bottom = top + (item.kind === "large" ? bounds.height : 1);
        for (let x = Math.max(0, Math.floor(left)); x < Math.min(cols, Math.ceil(left + bounds.width)); x++) {
          for (let y = Math.max(0, top); y < Math.min(rows, bottom); y++) {
            if (occupancy[x][y] !== "large") occupancy[x][y] = item.kind === "large" ? "large" : "text";
          }
        }
      });
    }
  });
  const blanks = new Set(scan.blank_cells.map(({ band, col, row }) => `${band}:${col}:${row}`));
  const result: Array<{ col: number; row: number; match: boolean }> = [];
  for (let col = 0; col < cols; col++) {
    const band = 7 - Math.floor(col / 2), localCol = col % 2;
    const box = scan.bands[band];
    if (!box) continue;
    const [left, top, right, bottom] = box;
    const cw = (right - left) / 2, ch = (bottom - top) / rows;
    for (let row = 0; row < rows; row++) {
      if (occupancy[col][row] === "large") continue;
      const renderBlank = occupancy[col][row] === "blank";
      const scanBlank = blanks.has(`${band}:${localCol}:${row}`);
      if (!renderBlank && !scanBlank) continue;
      const x1 = left + localCol * cw, y1 = top + row * ch;
      const x2 = x1 + cw, y2 = y1 + ch;
      // 与扫描空格识别一致：图像外／退化的小格不能判为不匹配。
      if (!(0 <= x1 && x1 < x2 && x2 <= scan.width && 0 <= y1 && y1 < y2 && y2 <= scan.height)) continue;
      if (Math.floor(x2 - cw * .16) - Math.ceil(x1 + cw * .16) < 4 ||
          Math.floor(y2 - ch * .16) - Math.ceil(y1 + ch * .16) < 4) continue;
      result.push({ col, row, match: renderBlank && scanBlank });
    }
  }
  return result;
}

/** 只给定位器非空字格的行跨度；空格占位保留，但不作为墨迹拟合目标。
 *  按固定版框的实际列坐标归属，短页补空列，越界内容不挤入网格。 */
export function scanGridPrior(page: L3Page): RowSpan[][] {
  const { config } = page;
  if (config.expectedBands !== 8 || config.smallColumnsPerBand !== 2 ||
      config.rowCap !== 24 || config.largeCols !== 2 || config.largeRows !== 2) {
    throw new Error("原图字格暂仅支持康熙字典 8×12 版式");
  }
  const { colOffset } = getPageFrame(page);
  const spans = Array.from({ length: 8 }, () => new Map<string, RowSpan>());
  page.bands.forEach((band, bi) => {
    const left = page.colStarts[bi] + colOffset;
    for (const item of band.items) {
      const bounds = getItemBounds(item, config);
      const x = left + bounds.x;
      const cells = item.kind === "large" ? [item.text] : item.cells;
      cells.forEach((text, i) => {
        const start = item.r + (item.kind === "large" ? 0 : i);
        const end = start + (item.kind === "large" ? config.largeRows : 1);
        if (!text.trim() || start < 0 || end > config.rowCap) return;
        for (let j = 0; j < 8; j++) {
          const bandLeft = 14 - j * 2;
          if (x < bandLeft + 2 && x + bounds.width > bandLeft) {
            spans[j].set(`${start}:${end}`, [start, end]);
          }
        }
      });
    }
  });
  return spans.map((band) => [...band.values()].sort(([a, b], [c, d]) => a - c || b - d));
}
