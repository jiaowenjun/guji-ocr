// 编辑器 ↔ 渲染列联动（IR 版）：光标偏移 → 大行/书名高亮；点击行 → 光标落点。
// 替代此前的 locate.ts：偏移直接来自 IR 的 src（原始文本区间），不再有并行推导。
import type { BookRuns, IRBand, IRDocument, IRSegment } from "./types";
import { bandKey } from "./types";

type BookSeg = Extract<IRSegment, { kind: "book" }>;

function bandsOf(doc: IRDocument): IRBand[] {
  return doc.pages.flatMap((p) => p.bands);
}

function pageOfBand(doc: IRDocument, band: IRBand): number {
  return doc.pages.find((p) => p.bands.includes(band))!.no;
}

function bandById(doc: IRDocument, id: string): IRBand | undefined {
  return bandsOf(doc).find((b) => b.id === id);
}

/** 光标 → 渲染高亮（页声明行/文件头无大行；间隙取前一大行） */
export function highlightAt(doc: IRDocument, cursor: number | null): {
  band: { page: number; index: number } | null;
  book: BookRuns | null;
} {
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

  // 光标所在书名区间 → 各行内 item 序号段（延续行的书名块是行内第 0 个）
  let book: BookRuns | null = null;
  outer: for (const page of doc.pages) {
    for (const b of page.bands) {
      for (const seg of b.segments) {
        if (seg.kind !== "book" || !seg.src) continue;
        const [s0, s1] = seg.src;
        if (cursor < s0 || cursor > s1) continue;
        book = runsFor(doc, seg);
        break outer;
      }
    }
  }
  return {
    band: band ? { page: pageOfBand(doc, band), index: band.ord } : null,
    book,
  };
}

function runsFor(doc: IRDocument, seg: BookSeg): BookRuns {
  const runs: BookRuns = {};
  const [s0] = seg.src!;
  for (const part of seg.parts) {
    const target = part.band ? bandById(doc, part.band) : openerBandOf(doc, seg);
    if (!target?.src) continue;
    const openerBand = openerBandOf(doc, seg);
    const isOpenerBand = target === openerBand;
    const start = isOpenerBand ? booksOpenedBeforeInBand(target, s0) : 0;
    const count = part.text.split("\n").length;
    const key = bandKey(pageOfBand(doc, target), target.ord);
    (runs[key] ??= []).push({ start, count });
  }
  return Object.keys(runs).length ? runs : {};
}

function openerBandOf(doc: IRDocument, seg: BookSeg): IRBand | undefined {
  const s0 = seg.src![0];
  return bandsOf(doc).find((b) => b.src && s0 >= b.src[0] && s0 < b.src[1]);
}

function booksOpenedBeforeInBand(band: IRBand, before: number): number {
  let n = 0;
  for (const s of band.segments) {
    if (s.kind === "book" && s.src && s.src[0] >= band.src![0] && s.src[0] < before) n++;
  }
  return n;
}

/** 点击渲染行 → 编辑器光标落点（该行首个非空白字符） */
export function bandCursorTarget(doc: IRDocument, text: string, page: number, index: number): number | null {
  const band = doc.pages.find((p) => p.no === page)?.bands.find((b) => b.ord === index);
  if (!band?.src) return null;
  const lead = /^\s*/.exec(text.slice(band.src[0], band.src[1]));
  return band.src[0] + (lead ? lead[0].length : 0);
}
