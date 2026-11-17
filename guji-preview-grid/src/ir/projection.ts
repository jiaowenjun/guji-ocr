// Overlay geometry is a projection over placements, never part of the skeleton.
import type { IROverlay } from "./types";
import type { L3Item, L3Page } from "./layout3";

export interface BookBox {
  overlayId: string;
  bandIdx: number;
  rowStart: number;
  rowEnd: number;
  col: number;
  openTop: boolean;
  openBottom: boolean;
  halfShift?: 0.5;
  cols?: number;
}

export interface LocatedRun {
  page: L3Page;
  bandIdx: number;
  item: L3Item;
}

export function indexLayout(pages: L3Page[]): Map<string, LocatedRun[]> {
  const byLine = new Map<string, LocatedRun[]>();
  for (const page of pages) page.bands.forEach((band, bandIdx) => {
    for (const id of band.lineIds) if (!byLine.has(id)) byLine.set(id, []);
    for (const item of band.items) {
      if (item.lineId === undefined) continue;
      const runs = byLine.get(item.lineId) ?? [];
      runs.push({ page, bandIdx, item });
      byLine.set(item.lineId, runs);
    }
  });
  for (const runs of byLine.values()) runs.sort((a, b) => (a.item.cpStart ?? 0) - (b.item.cpStart ?? 0));
  return byLine;
}

export function projectBooks(pages: L3Page[], overlays: IROverlay[], index = indexLayout(pages)): Map<L3Page, BookBox[]> {
  const boxes = new Map(pages.map((p) => [p, [] as BookBox[]]));
  for (const overlay of overlays) {
    if (overlay.kind !== "book-title") continue;
    // The IR span array carries GLOBAL reading order, including off-page spans.
    const fragments: Array<{ page: L3Page; spanIndex: number; box: BookBox }> = [];
    const missing = [0];
    for (const span of overlay.spans) missing.push(missing.at(-1)! + (index.has(span.line) ? 0 : 1));
    overlay.spans.forEach((span, spanIndex) => {
      for (const { page, bandIdx, item } of index.get(span.line) ?? []) {
        if (item.kind === "large") {
          if ((item.cpStart ?? 0) < span.range[1] && (item.cpEnd ?? 0) > span.range[0]) {
            const col = page.colStarts[bandIdx] + item.c;
            const prev = fragments.at(-1);
            if (prev?.page === page && prev.spanIndex === spanIndex && prev.box.bandIdx === bandIdx &&
                prev.box.col === col && prev.box.cols === page.config.largeCols && prev.box.rowEnd === item.r) {
              prev.box.rowEnd += page.config.largeRows;
            } else fragments.push({ page, spanIndex, box: {
              overlayId: overlay.id, bandIdx, rowStart: item.r, rowEnd: item.r + page.config.largeRows,
              col, cols: page.config.largeCols, openTop: false, openBottom: false,
            } });
          }
          continue;
        }
        const ranges = item.rawRanges ?? (item.rawOffsets ?? []).map((cp): [number, number] => [cp, cp + 1]);
        let first = -1;
        let last = -1;
        ranges.forEach(([a, b], k) => {
          if (a < span.range[1] && b > span.range[0]) {
            if (first < 0) first = k;
            last = k;
          }
        });
        if (first < 0) continue;
        fragments.push({ page, spanIndex, box: {
          overlayId: overlay.id, bandIdx,
          rowStart: item.r + first, rowEnd: item.r + last + 1,
          col: page.colStarts[bandIdx] + item.c, halfShift: item.halfShift,
          openTop: false, openBottom: false,
        } });
      }
    });
    fragments.forEach(({ page, spanIndex, box }, i) => {
      // Missing lines may belong to pages outside the rendered subset. Preserve
      // those continuations, while punctuation-only spans need no visible frame.
      const unseenBefore = missing[spanIndex] > 0;
      const unseenAfter = missing.at(-1)! > missing[spanIndex + 1];
      box.openTop = i > 0 || unseenBefore || overlay.openedHere === false;
      box.openBottom = i < fragments.length - 1 || unseenAfter || overlay.closed === false;
      boxes.get(page)!.push(box);
    });
  }
  return boxes;
}

/** A line can contain multiple runs separated by large glyphs. Select one item. */
export function locateCell(index: Map<string, LocatedRun[]>, lineId: string, cp: number): { item: L3Item; index: number } | null {
  let hit: { item: L3Item; index: number } | null = null;
  let best = -1;
  for (const { item } of index.get(lineId) ?? []) {
    if (item.kind !== "run") continue;
    for (const [i, offset] of (item.rawOffsets ?? []).entries()) {
      if (offset <= cp && offset >= best) {
        hit = { item, index: i };
        best = offset;
      }
    }
  }
  return hit;
}
