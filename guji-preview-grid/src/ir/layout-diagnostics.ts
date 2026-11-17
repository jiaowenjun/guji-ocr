import type { L3Page } from "./layout3";
import { getItemBounds } from "./layout-geometry";

export interface LayoutDiagnostic {
  code: "band-count" | "page-width" | "band-width" | "empty-band" | "overflow" | "overlap";
  severity: "info" | "warning" | "error";
  page: number;
  bandId?: string;
  message: string;
}

/** Inspect geometry without correcting transcription or discarding clipped cells. */
export function diagnoseLayout(page: L3Page): LayoutDiagnostic[] {
  const out: LayoutDiagnostic[] = [];
  const { rowCap, expectedBands, smallColumnsPerBand } = page.config;
  const add = (code: LayoutDiagnostic["code"], message: string, bandId?: string, severity: LayoutDiagnostic["severity"] = "warning") =>
    out.push({ code, severity, page: page.no, bandId, message });
  if (expectedBands !== null) {
    if (page.bands.length > expectedBands) add("band-count", `大列数 ${page.bands.length}，超出版面 ${expectedBands}`);
    if (page.totalCols > expectedBands * smallColumnsPerBand)
      add("page-width", `页宽 ${page.totalCols} 格，版框 ${expectedBands * smallColumnsPerBand} 格，左侧 ${page.totalCols - expectedBands * smallColumnsPerBand} 小列已隐藏`);
  }
  for (const band of page.bands) {
    if (band.cols !== smallColumnsPerBand) add("band-width", `此大列宽 ${band.cols} 格，预期 ${smallColumnsPerBand} 格`, band.id);
    if (!band.items.length) add("empty-band", "保留的空大列", band.id, "info");
    if (band.rows > rowCap) add("overflow", `此列 ${band.rows} 格，超出版面 ${rowCap} 格，底部 ${band.rows - rowCap} 格已隐藏`, band.id);
    const occupied = new Set<string>();
    let overlap = false;
    // Half-cell columns account for centered one-column runs (halfShift).
    for (const item of band.items) {
      const { x, y, width, height } = getItemBounds(item, page.config);
      const left = 2 * x;
      for (let row = y; row < y + height; row++) for (let col = left; col < left + 2 * width; col++) {
        const key = `${row}:${col}`;
        if (occupied.has(key)) overlap = true;
        occupied.add(key);
      }
    }
    if (overlap) add("overlap", "此大列存在字格重叠", band.id, "error");
  }
  return out;
}
