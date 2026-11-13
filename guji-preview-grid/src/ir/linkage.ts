// 编辑器 ↔ 渲染列联动（IR v2 版）：光标偏移 → 大行/书名高亮；点击行 → 光标落点。
// 大行定位用 band.src（原始文本区间）；书名用页级 semantics.books overlay，
// 各行内 item 序号 = 该行 title 锚在元素序中的位置（延续行锚始终在行首附近）。
import type { BookRuns, IRBand, IRDocument, IRLine } from "./types";
import { bandKey } from "./types";

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
): { band: { page: number; index: number } | null; book: BookRuns | null } {
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

  // 光标所在书名（overlay src 含区间）→ 各大行内 item 序号段
  let book: BookRuns | null = null;
  if (band) {
    const page = doc.pages.find((p) => p.bands.includes(band))!;
    const bk = page.semantics.books.find((b) => b.src && cursor >= b.src[0] && cursor <= b.src[1]);
    if (bk) {
      book = {};
      // 按大行分组 spans；行内 item 序号 = 该行 title 锚的元素序（以行内 title 计数）
      const byBand = new Map<IRBand, number>(); // band → 该书首个锚前的 title 锚数
      const spanCount = new Map<IRBand, number>();
      for (const span of bk.spans) {
        let lineOwner: IRLine | undefined;
        let bandOwner: IRBand | undefined;
        for (const b2 of bandsOf(doc)) {
          const l = b2.lines.find((x) => x.id === span.line);
          if (l) {
            lineOwner = l;
            bandOwner = b2;
            break;
          }
        }
        if (!bandOwner || !lineOwner) continue;
        spanCount.set(bandOwner, (spanCount.get(bandOwner) ?? 0) + 1);
        if (!byBand.has(bandOwner)) {
          // 该书在 bandOwner 的首个锚位置：遍历行元素数 title 出现次数
          let seen = 0;
          let start = 0;
          outer: for (const line of bandOwner.lines) {
            for (const el of line.elements) {
              if (el.sem === "title") {
                if (el.ref === bk.id) {
                  start = seen;
                  break outer;
                }
                seen++;
              }
            }
          }
          byBand.set(bandOwner, start);
        }
      }
      for (const [b2, count] of spanCount) {
        (book ??= {})[bandKey(pageOfBand(doc, b2), b2.ord)] = [
          { start: byBand.get(b2) ?? 0, count },
        ];
      }
    }
  }
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
