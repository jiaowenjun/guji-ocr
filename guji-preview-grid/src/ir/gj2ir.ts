// .gj 文本 → Guji IR v2（页→大行→小行；大字/小字元素；书名 overlay）。
// 词法与 v1 同源（镜像 parse-inline 状态机，消费 lineTransform 后的大行文本），
// 按物理行组织：每行按「书名区域 ∩ 本行 / 普通片」交替切分；区域的本行片段
// 成为一个 sem=title 锚元素（就地定位）；跨行书名在页级 semantics.books 登记
// spans（行 id + 行内字符区间）并与锚元素互引（ref）。
// 对等性契约（test/ir.spec.ts）：ir2blocks(gj2ir(t)) === parsePages(t)。
import type {
  IRBand,
  IRBook,
  IRDocument,
  IRElement,
  IRLine,
  IRPage,
} from "./types";
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
  text: string; // 逐行 lineTransform 后 join —— 词法输入
  chunkText: string; // 块级变换后（判存活/页声明）
  lineRanges: Array<[number, number]>; // 与 text 的行一一对应（原始文本区间）
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
  let lineRanges: Array<[number, number]> = [];
  let started = false;

  const flush = () => {
    if (!started) return;
    const joined = lines.join("\n");
    const chunkText = chunkTransform(joined);
    if (chunkText.length > 0)
      chunks.push({ from: chunkFrom, to: chunkTo, text: joined, chunkText, lineRanges });
    started = false;
    lines = [];
    lineRanges = [];
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
        lineRanges.push([lineStart, i]);
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

/** 大行文本（lineTransform 后）内的书名区域：[from, to) 字符区间（含括号） */
interface LocalRegion {
  from: number;
  to: number;
  kind: "closed" | "opener" | "continuation"; // 行中孤立 】 按 continuation（parser 语义）
}

function detectRegions(source: string): LocalRegion[] {
  const regions: LocalRegion[] = [];
  const cont = /^[^\【】]*\】/.exec(source);
  if (cont) regions.push({ from: 0, to: cont[0].length, kind: "continuation" });
  const re = /\【[\s\S]*?\】|\【[^\】]*$/g;
  re.lastIndex = cont ? cont[0].length : 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source))) {
    regions.push({
      from: m.index,
      to: m.index + m[0].length,
      kind: m[0].endsWith("】") ? "closed" : "opener",
    });
  }
  // 行中孤立 】（未被任何区域覆盖）：parser 语义同样产出书名片段
  const reOrphan = /\】/g;
  reOrphan.lastIndex = cont ? cont[0].length : 0;
  while ((m = reOrphan.exec(source))) {
    if (!regions.some((r) => m!.index >= r.from && m!.index < r.to)) {
      regions.push({ from: m.index, to: m.index + 1, kind: "continuation" });
    }
  }
  return regions.sort((a, b) => a.from - b.from);
}

/** 普通片词法（区域内字符由调用方剔除；镜像 parse-inline 状态机） */
function tokenizePlain(source: string, makeId: () => string): IRElement[] {
  const elements: IRElement[] = [];
  let frag = "";
  const consume = () => {
    if (frag.length > 0) {
      elements.push({ id: makeId(), class: "small", sem: "gloss", text: frag });
      frag = "";
    }
  };
  let i = 0;
  while (i < source.length) {
    const c = source[i];
    if (c === "/" && source[i + 1] === "/") break; // 行内注释截断
    if (c === "#") {
      consume();
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
        if (inner)
          elements.push({ id: makeId(), class: "large", sem: "mark", text: inner, style: "circled" });
        i = j;
        continue;
      }
      const cp = source.codePointAt(i + 1);
      const ch = cp !== undefined ? String.fromCodePoint(cp) : undefined;
      if (ch !== undefined && isOrdinary(ch)) {
        elements.push({
          id: makeId(),
          class: "large",
          sem: "head",
          text: ch === "*" ? " " : ch,
        });
        i += 1 + ch.length;
        continue;
      }
      i++;
      continue;
    }
    frag += c === "*" ? " " : c;
    i++;
  }
  consume();
  return elements;
}

/** .gj → IR v2 文档 */
export function gj2ir(text: string): IRDocument {
  const { chunks, pageOf } = walkChunks(text);
  const spans = locateSpans(text);
  const pages: IRPage[] = [];
  // 锚元素 → {所属区域序号, 所属行}（函数内局部；装配 overlay 用）
  const anchorMeta = new Map<string, { ri: number; line: IRLine }>();

  for (const c of chunks) {
    const pageM = /^@(\d+)$/.exec(c.chunkText);
    if (pageM) {
      pages.push({
        id: `p${pageM[1].padStart(4, "0")}`,
        no: Number(pageM[1]),
        src: [c.from, c.to],
        bands: [],
        semantics: { books: [] },
      });
      continue;
    }
    const pageNo = pageOf.get(c) ?? 0;
    if (pageNo === 0 || pages.length === 0) continue;
    const page = pages[pages.length - 1];
    const bandId = `${page.id}-b${page.bands.length}`;
    const band: IRBand = { id: bandId, ord: page.bands.length, src: [c.from, c.to], lines: [] };

    const headingM = /^(#+) (.*)$/.exec(c.text.trim());
    if (headingM && !c.text.trim().includes("\n")) {
      band.heading = { level: Math.min(3, headingM[1].length) as 1 | 2 | 3, text: headingM[2] };
      page.bands.push(band);
      continue;
    }

    // ---- 逐行词法：按「书名区域 ∩ 本行 / 普通片」交替切分 ----
    const regions = detectRegions(c.text);
    let seg = 0;
    const nextId = () => `${bandId}-e${seg++}`;

    const lineSources = c.text.split("\n");
    let base = 0;
    lineSources.forEach((lineSource, li) => {
      const elements: IRElement[] = [];
      const anchorsThisLine: Array<{ el: IRElement; ri: number }> = [];
      let i = 0;
      while (i < lineSource.length) {
        const pos = base + i;
        const region = regions.find((r) => pos >= r.from && pos < r.to);
        if (region) {
          // 本行的区域片段：一个锚元素就地定位（跨行书名的每行各一锚）
          const anchor: IRElement = { id: nextId(), class: "small", sem: "title", text: "" };
          elements.push(anchor);
          anchorsThisLine.push({ el: anchor, ri: regions.indexOf(region) });
          while (i < lineSource.length && base + i < region.to) {
            const ch = lineSource[i];
            if (ch !== "【" && ch !== "】") anchor.text += ch === "*" ? " " : ch;
            i++;
          }
          continue;
        }
        // 普通片：到本行内下一个区域起点为止
        const nextStart = regions
          .filter((r) => r.from > pos && r.from < base + lineSource.length)
          .reduce((min, r) => Math.min(min, r.from), base + lineSource.length);
        const plainEnd = nextStart - base;
        if (plainEnd > i) {
          elements.push(...tokenizePlain(lineSource.slice(i, plainEnd), nextId));
          i = plainEnd;
        } else {
          i++; // 理论不可达（区域外的字符必属某普通片）
        }
      }
      const line: IRLine = {
        id: `${bandId}-l${li}`,
        ord: li,
        src: c.lineRanges[li],
        elements,
      };
      band.lines.push(line);
      for (const a of anchorsThisLine) anchorMeta.set(a.el.id, { ri: a.ri, line });
      base += lineSource.length + 1;
    });
    page.bands.push(band);
  }

  // ---- 跨行书名 overlay 装配：同一原始 span 的开启/延续区域合并为单一书 ----
  const spanKey = (s: [number, number]) => `${s[0]}:${s[1]}`;
  const bookBySpan = new Map<string, IRBook>();
  for (const page of pages) {
    for (const band of page.bands) {
      const chunk = chunks.find((c) => c.from === band.src![0] && c.to === band.src![1]);
      if (!chunk) continue;
      const regions = detectRegions(chunk.text);
      const [b0, b1] = band.src!;
      const openSpans = spans.filter(([s0]) => s0 >= b0 && s0 < b1).sort((x, y) => x[0] - y[0]);
      const contSpans = spans.filter(([s0, s1]) => s0 < b0 && s1 > b0).sort((x, y) => x[0] - y[0]);
      const contRegions = regions.filter((r) => r.kind === "continuation");
      const openRegions = regions.filter((r) => r.kind !== "continuation");

      const attach = (region: LocalRegion, span: [number, number] | null, viaOpener: boolean) => {
        const ri = regions.indexOf(region);
        let book: IRBook | undefined = span ? bookBySpan.get(spanKey(span)) : undefined;
        if (!book) {
          // 开启行建书（登记在开启行所属页）；延续行遇到未见过的 span（跨页/异常）按独立书
          if (!viaOpener && span) return; // 开启行还没处理——顺序上不应发生，防御
          book = { id: `${page.id}-bk${page.semantics.books.length}`, spans: [] };
          if (span) {
            book.src = span;
            bookBySpan.set(spanKey(span), book);
          }
          page.semantics.books.push(book);
        }
        for (const line of band.lines) {
          const idx = line.elements.findIndex(
            (e) => e.sem === "title" && anchorMeta.get(e.id)?.ri === ri && anchorMeta.get(e.id)?.line === line,
          );
          if (idx < 0) continue;
          const el = line.elements[idx];
          const start = line.elements.slice(0, idx).reduce((n, e) => n + e.text.length, 0);
          book.spans.push({ line: line.id, range: [start, start + el.text.length] });
          el.ref = book.id;
        }
      };

      // 先开启后延续（同 span 合并；开启行始终先到——bands 按序）
      openRegions.forEach((r, k) => attach(r, openSpans[k] ?? null, true));
      contRegions.forEach((r, k) => {
        const span = contSpans[k] ?? null;
        if (span && bookBySpan.has(spanKey(span))) attach(r, span, false);
        else attach(r, span, true); // 孤立延续（无开启）成独立书
      });
    }
  }

  return {
    version: 2,
    meta: {
      sourceFormat: "gj",
      generatedBy: "guji-ir/2",
      fidelity: "full",
      profile: GUJI_PROFILE,
      lineLayout: "fold",
      orientation: "vertical-rtl",
    },
    pages,
  };
}
