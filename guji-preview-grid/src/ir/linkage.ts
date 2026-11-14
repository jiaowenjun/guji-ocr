// 编辑器 ↔ 渲染列联动（IR v3）：光标偏移 → 大行/书名 overlay/单字；点击行 → 光标落点。
// 大行定位用 band.src（UTF-16 原文区间，仅联动/溯源）；书名命中用 overlay.src；
// 单字定位用 line.cpSrcs（行规范文本各码点的原文偏移——语法字符无条目，
// 光标落在不产出字符的位置时回退到前一产出字符，与 highlightAt 间隙取前行同语义）。
import type { CharHighlight, IRBand, IRDocument, IRLine } from "./types";

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

/** 点击渲染行 → 编辑器光标落点：首个产出字符之后（单字联动随即点亮该行首字；
 *  无产出字符的空大行退回首非空白字符） */
export function bandCursorTarget(
  doc: IRDocument,
  text: string,
  page: number,
  index: number,
): number | null {
  const band = doc.pages.find((p) => p.no === page)?.bands.find((b) => b.ord === index);
  if (!band?.src) return null;
  const first = band.lines.flatMap((l) => l.cpSrcs ?? [])[0];
  if (first !== undefined) {
    const ch = String.fromCodePoint(text.codePointAt(first)!);
    return first + ch.length;
  }
  const lead = /^\s*/.exec(text.slice(band.src[0], band.src[1]));
  return band.src[0] + (lead ? lead[0].length : 0);
}

// ---- 单字联动：光标前一字符 → 渲染字格 ----

/** cpSrcs 扁平化（阅读序 = 原文序，src 非降序可二分；合字各字共享偏移） */
export interface CharIndexEntry {
  lineId: string;
  cp: number;
  src: number;
}
export type CharIndex = CharIndexEntry[];

export function buildCharIndex(doc: IRDocument): CharIndex {
  const entries: CharIndex = [];
  for (const p of doc.pages)
    for (const b of p.bands)
      for (const l of b.lines) {
        const srcs = l.cpSrcs ?? [];
        for (let cp = 0; cp < srcs.length; cp++) entries.push({ lineId: l.id, cp, src: srcs[cp] });
      }
  return entries;
}

const cpLen = (s: string) => [...s].length;

/** 光标前一字符 → 单字定位（large=大字/合字格元素；cell=小字格行+码点）。
 *  前一字符不产出（#、【】、换行、@页声明、注释）或已被清洗（标点）时
 *  回退到前一产出字符——校对时光标任意移动都有「我在哪个字」的反馈 */
export function charHighlightAt(
  doc: IRDocument,
  index: CharIndex,
  text: string,
  cursor: number | null,
): CharHighlight | null {
  if (cursor === null || cursor <= 0 || index.length === 0) return null;
  // 前一字符的原文起点：光标在代理对之后需多退一格（ext-B 字头高频）
  let s = cursor - 1;
  const c1 = text.charCodeAt(s);
  if (s > 0 && c1 >= 0xdc00 && c1 <= 0xdfff) s -= 1;
  // 二分取最后一个 src <= s 的产出字符
  let lo = 0;
  let hi = index.length - 1;
  let hit = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (index[mid].src <= s) {
      hit = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  if (hit < 0) return null;
  const { lineId, cp } = index[hit];
  const line: IRLine | undefined = doc.pages
    .flatMap((p) => p.bands)
    .find((b) => b.lines.some((l) => l.id === lineId))
    ?.lines.find((l) => l.id === lineId);
  if (!line) return null;
  // 行规范码点 → 元素（行内累计码点数；合字命中即整格）
  let acc = 0;
  for (const el of line.elements) {
    const n = cpLen(el.text);
    if (cp < acc + n) {
      return el.class === "large" ? { kind: "large", elId: el.id } : { kind: "cell", lineId, cp };
    }
    acc += n;
  }
  return null;
}
