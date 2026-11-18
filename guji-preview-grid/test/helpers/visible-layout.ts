import type { IRDocument } from "../../src/ir/types";
import { layout3 } from "../../src/ir/layout3";
import { projectBooks } from "../../src/ir/projection";
import { irToText } from "../../src/ir/text";
/** Ignore opaque IDs/provenance, compare every cell (including blanks) and decoration. */
export function visibleLayout(doc: IRDocument) {
  const laid = layout3(doc), books = projectBooks(laid, doc.overlays);
  return { text: irToText(doc), pages: laid.map(p => ({ page: p.no, cols: p.totalCols, bands: p.bands.map(b => ({
    cols: b.cols, rows: b.rows,
    cells: b.items.flatMap(i => i.kind === "large" ? [{
      r: i.r, c: i.c, text: i.text, size: "large", ligature: !!i.ligature,
      circle: doc.overlays.some(o => o.kind === "circle" && o.target === i.elId),
    }] : i.cells.map((ch, k) => ({ r: i.r + k, c: i.c + (i.halfShift ?? 0), text: ch, size: "small" })))
      .sort((a, b) => a.r - b.r || a.c - b.c || a.size.localeCompare(b.size)),
  })), books: (books.get(p) ?? []).map(b => ({ band: b.bandIdx, r: b.rowStart, end: b.rowEnd,
    c: b.col + (b.halfShift ?? 0), width: b.cols ?? 1, openTop: b.openTop, openBottom: b.openBottom }))
      .sort((a, b) => a.band - b.band || a.c - b.c || a.r - b.r),
  })) };
}
