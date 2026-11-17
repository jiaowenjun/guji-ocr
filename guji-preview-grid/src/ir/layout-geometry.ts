import type { IRLayoutConfig } from "./layout-config";
import type { L3Item } from "./layout3";

/** 完整占格范围（band 局部坐标，未裁剪）；半格居中仍以小格为单位。 */
export function getItemBounds(item: L3Item, config: IRLayoutConfig) {
  return {
    x: item.c + (item.kind === "run" ? item.halfShift ?? 0 : 0),
    y: item.r,
    width: item.kind === "large" ? config.largeCols : 1,
    height: item.kind === "large" ? config.largeRows : item.cells.length,
  };
}
