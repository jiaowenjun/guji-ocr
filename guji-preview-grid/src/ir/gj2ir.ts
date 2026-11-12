// .gj 文本 → Guji IR（语义结构，保真：标点/折行保留，剔除属 profile）。
// 词法镜像 parse-inline.ts 的状态机（含 quirk：#( 带圈双前瞻、书名跨行、行内
// // 截断、字面 * 尾随空格），消费 lineTransform 后的大行文本（与 parser 的
// 输入同层，空格语义天然一致）；大行切分吸收自 locate.ts 的行走。跨行书名
// 的 parts 与 src 基于全文原始偏移配对（供编辑器联动）。
// 对等性契约在 test/ir.spec.ts：ir2blocks(gj2ir(t)) === parsePages(t)。
import type { IRBand, IRDocument, IRPage, IRSegment } from "./types";
import { GUJI_PROFILE } from "./types";

const chunkTransform = (s: string) =>
  s
    .trim()
    .replace(/[。，·":：、《》]/g, "")
    .replace(/\/\/.*/, "")
    .replace(/[◎〇]/g, "○");

const lineTransform = (line: string) =>
  line.replace(/　/g, "*").trim().replace(/[ \t]+/, " ");

interface RawChunk {
  from: number;
  to: number;
  text: string; // 逐行 lineTransform 后 join —— 词法输入（与 parser 同层）
  chunkText: string; // 块级变换后（判存活/页声明）
}

/** 块切分（带偏移；语义 === split()）：存活块按位置序，页块与大行块混排 */
function walkChunks(text: string): { chunks: RawChunk[]; pageOf: Map<RawChunk, number> } {
  let liveStart = 0;
  const cut = /[\s\S]*==.*/.exec(text);
  if (cut) {
    liveStart = cut.index + cut[0].length;
    if (text[liveStart] === "\n") liveStart += 1;
  }
  const chunks: RawChunk[] = [];
  let chunkFrom = -1;
  let chunkTo = 0;
  let lines: string[] = [];
  let started = false;

  const flush = () => {
    if (!started) return;
    const joined = lines.join("\n");
    const chunkText = chunkTransform(joined);
    if (chunkText.length > 0) chunks.push({ from: chunkFrom, to: chunkTo, text: joined, chunkText });
    started = false;
    lines = [];
  };

  let lineStart = liveStart;
  for (let i = liveStart; i <= text.length; i++) {
    if (i === text.length || text[i] === "\n") {
      const t = lineTransform(text.slice(lineStart, i));
      if (t === "") flush();
      else {
        if (!started) {
          started = true;
          chunkFrom = lineStart;
        }
        chunkTo = i;
        lines.push(t);
      }
      lineStart = i + 1;
    }
  }
  flush();

  const pageOf = new Map<RawChunk, number>();
  let cur = 0;
  for (const c of chunks) {
    const m = /^@(\d+)$/.exec(c.chunkText);
    if (m) cur = Number(m[1]);
    else pageOf.set(c, cur);
  }
  return { chunks, pageOf };
}

/** 全文原始偏移上的书名区间：【…】 惰性配对（含括号）；未闭合【到文末 */
function locateSpans(text: string): Array<[number, number]> {
  const spans: Array<[number, number]> = [];
  const re = /\【[\s\S]*?\】/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) spans.push([m.index, m.index + m[0].length]);
  const lastPaired = spans.length ? spans[spans.length - 1][1] : 0;
  const unclosed = text.indexOf("【", lastPaired);
  if (unclosed !== -1) spans.push([unclosed, text.length]);
  return spans;
}

const isOrdinary = (c: string) => !"#【】\n".includes(c);

interface LocalBook {
  slot: number; // 在 segments 中的占位下标
  kind: "closed" | "opener" | "continuation";
  text: string; // 本行内的书名文本（去括号，*→空格）
}

/**
 * 单个大行的保真词法（输入为 lineTransform 后的大行文本）。
 * 书名只记录占位与文本；跨行 parts 与原始区间在装配阶段经全文 span 配对。
 */
function tokenizeBand(bandId: string, source: string): { segments: IRSegment[]; books: LocalBook[] } {
  const segments: IRSegment[] = [];
  const books: LocalBook[] = [];
  let frag = "";
  let seg = 0;
  const nextId = () => `${bandId}-s${seg++}`;

  const pushBook = (kind: LocalBook["kind"], text: string) => {
    books.push({ slot: segments.length, kind, text });
    segments.push({ kind: "book", id: nextId(), parts: [] });
  };
  const consumeFrag = () => {
    if (frag.length > 0) {
      segments.push({ kind: "text", id: nextId(), text: frag });
      frag = "";
    }
  };

  // 行首孤儿延续（^…】）——parser 的 book-end 语义
  const cont = /^[^\【】\n]*\】/.exec(source);
  if (cont) {
    pushBook("continuation", cont[0].slice(0, -1).replace(/\*/g, " "));
  }

  let i = cont ? cont[0].length : 0;
  while (i < source.length) {
    const c = source[i];

    if (c === "/" && source[i + 1] === "/") {
      while (i < source.length && source[i] !== "\n") i++;
      continue;
    }

    if (c === "【") {
      consumeFrag();
      const close = source.indexOf("】", i);
      if (close === -1) {
        // 开启未闭合（本行内）：到行尾
        pushBook("opener", source.slice(i + 1).replace(/\*/g, " "));
        i = source.length;
      } else {
        pushBook("closed", source.slice(i + 1, close).replace(/\*/g, " "));
        i = close + 1;
      }
      continue;
    }
    if (c === "】") {
      // 行中孤立的 】（无开启）：按 parser 语义成 book-end 片
      consumeFrag();
      pushBook("continuation", "");
      i++;
      continue;
    }

    if (c === "\n") {
      consumeFrag();
      segments.push({ kind: "br" });
      i++;
      continue;
    }

    if (c === "#") {
      consumeFrag();
      const n1 = source[i + 1];
      if (n1 === "(") {
        let j = i + 2;
        let inner = "";
        if (source[j + 1] === ")" || source[j + 2] === ")") {
          while (j < source.length && source[j] !== ")" && isOrdinary(source[j])) {
            inner += source[j] === "*" ? " " : source[j];
            j++;
          }
          if (source[j] === ")") j++;
        } else if (j < source.length && isOrdinary(source[j])) {
          inner = source[j] === "*" ? " " : source[j];
          j++;
        } else {
          j = i + 2;
        }
        if (inner) segments.push({ kind: "mark", id: nextId(), text: inner, style: "circled" });
        i = j;
        continue;
      }
      const cp = n1 !== undefined ? String.fromCodePoint(source.codePointAt(i + 1) ?? 0) : undefined;
      const ch = cp !== undefined && [...cp].length === 1 && (cp === "*" || cp === " ") ? cp : cp;
      if (ch !== undefined && isOrdinary(ch)) {
        // 字面 *（由　变换而来）按 parser 语义算作大字空格
        const headChar = ch === "*" ? " " : ch;
        segments.push({ kind: "head", id: nextId(), char: headChar });
        i += 1 + ch.length;
        continue;
      }
      i++;
      continue;
    }

    frag += c === "*" ? " " : c;
    i++;
  }
  consumeFrag();
  return { segments, books };
}

/** .gj → IR 文档 */
export function gj2ir(text: string): IRDocument {
  const { chunks, pageOf } = walkChunks(text);
  const spans = locateSpans(text);
  const pages: IRPage[] = [];

  for (const c of chunks) {
    const pageM = /^@(\d+)$/.exec(c.chunkText);
    if (pageM) {
      pages.push({ id: `p${pageM[1].padStart(4, "0")}`, no: Number(pageM[1]), src: [c.from, c.to], bands: [] });
      continue;
    }
    const pageNo = pageOf.get(c) ?? 0;
    if (pageNo === 0 || pages.length === 0) continue;
    const page = pages[pages.length - 1];
    const bandId = `${page.id}-b${page.bands.length}`;
    const band: IRBand = { id: bandId, ord: page.bands.length, src: [c.from, c.to], segments: [] };

    const headingM = /^(#+) (.*)$/.exec(c.text.trim());
    if (headingM && !c.text.trim().includes("\n")) {
      band.heading = { level: Math.min(3, headingM[1].length) as 1 | 2 | 3, text: headingM[2] };
    } else if (c.chunkText === "#") {
      // 独立 # 行：空大字列
    } else {
      band.segments = tokenizeBand(bandId, c.text).segments;
    }
    page.bands.push(band);
  }

  // ---- 跨行书名装配：按全文原始 span 把 opener/延续行的 part 与 src 挂上 ----
  const allBands = pages.flatMap((p) => p.bands);
  for (const band of allBands) {
    const [b0, b1] = band.src!;
    // 本行相关 span：开启（s0 落在本行）与延续（s0 在本行前且区间伸入本行）
    const openSpans = spans.filter(([s0]) => s0 >= b0 && s0 < b1).sort((x, y) => x[0] - y[0]);
    const contSpans = spans.filter(([s0, s1]) => s0 < b0 && s1 > b0).sort((x, y) => x[0] - y[0]);
    const localBooks = tokenizeBand(band.id, bandTextOf(band, chunks)).books;

    // 本地词法里按位置序：行首延续段在前，其后 closed/opener 依出现序。
    // 延续段按 s0 序、开启段按 s0 序分别与 contSpans / openSpans 对齐。
    const contLocals = localBooks.filter((b) => b.kind === "continuation");
    const openLocals = localBooks.filter((b) => b.kind !== "continuation");

    contLocals.forEach((lb, k) => {
      const seg = band.segments[lb.slot] as Extract<IRSegment, { kind: "book" }>;
      const span = contSpans[k] ?? null;
      if (span) seg.src = span;
      seg.parts = [{ text: lb.text, band: band.id }];
    });
    openLocals.forEach((lb, k) => {
      const seg = band.segments[lb.slot] as Extract<IRSegment, { kind: "book" }>;
      const span = openSpans[k] ?? null;
      if (span) {
        const [s0, s1] = span;
        seg.src = span;
        seg.parts = [{ text: lb.text, band: band.id }];
        // 后续延续行 part
        for (const other of allBands) {
          if (other === band) continue;
          const [c0, c1] = other.src!;
          if (c0 <= s0 || c0 >= s1) continue;
          seg.parts.push({
            text: text.slice(c0, Math.min(c1, s1)).replace(/[【】]/g, "").replace(/[　*]/g, " "),
            band: other.id,
          });
        }
      } else {
        seg.parts = [{ text: lb.text, band: band.id }];
      }
    });
  }

  function bandTextOf(b: IRBand, cs: RawChunk[]): string {
    const hit = cs.find((c) => c.from === b.src![0] && c.to === b.src![1]);
    return hit ? hit.text : "";
  }

  return {
    version: 1,
    meta: { sourceFormat: "gj", generatedBy: "guji-ir/1", fidelity: "full", profile: GUJI_PROFILE },
    pages,
  };
}
