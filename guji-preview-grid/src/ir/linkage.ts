// 编辑器 ↔ 渲染列联动（IR v3）：光标偏移 → 大行/书名 overlay；点击行 → 光标落点。
// 大行定位用 band.src（UTF-16 原文区间，仅联动/溯源）；书名命中用 overlay.src。
import type { IRBand, IRDocument } from "./types";

function bandsOf(doc: IRDocument): IRBand[] {
  return doc.pages.flatMap((p) => p.bands);
}

function pageOfBand(doc: IRDocument, band: IRBand): number {
  return doc.pages.find((p) => p.bands.includes(band))!.no;
}

/** 光标 → 渲染高亮（页声明行/文件头无大行；间隙取前一大行） */
export function highlightAt(
  doc: IRDocument,
  cursor: number | null,
): { band: { page: number; index: number } | null; book: string | null } {
  if (cursor === null) return { band: null, book: null };
  for (const p of doc.pages) {
    if (p.src && cursor >= p.src[0] && cursor <= p.src[1]) return { band: null, book: null };
  }
  let hit: IRBand | null = null;
  let prev: IRBand | null = null;
  for (const b of bandsOf(doc)) {
    if (!b.src) continue;
    if (cursor < b.src[0]) break;
    if (cursor <= b.src[1]) {
      hit = b;
      break;
    }
    prev = b;
  }
  const band = hit ?? prev;
  const book =
    doc.overlays.find(
      (o) => o.kind === "book-title" && o.src && cursor >= o.src[0] && cursor <= o.src[1],
    )?.id ?? null;
  return {
    band: band ? { page: pageOfBand(doc, band), index: band.ord } : null,
    book,
  };
}

/** 点击渲染行 → 编辑器光标落点（该大行首个非空白字符） */
export function bandCursorTarget(
  doc: IRDocument,
  text: string,
  page: number,
  index: number,
): number | null {
  const band = doc.pages.find((p) => p.no === page)?.bands.find((b) => b.ord === index);
  if (!band?.src) return null;
  const lead = /^\s*/.exec(text.slice(band.src[0], band.src[1]));
  return band.src[0] + (lead ? lead[0].length : 0);
}
