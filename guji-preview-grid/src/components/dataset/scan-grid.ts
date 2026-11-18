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
