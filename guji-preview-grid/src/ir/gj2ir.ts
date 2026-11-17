// .gj → generic IR: # selects large type to newline; overlays never determine size.
import type {
  IRBand,
  IRBookOverlay,
  IRDocument,
  IRElement,
  IRLine,
  IROverlay,
  IRPage,
} from "./types";
import { GUJI_PROFILE } from "./types";
import { scanInline } from "../parser/inline-tokens";
import { isBlankBand } from "../parser/structure";

const chunkTransform = (s: string) =>
  s
    .trim()
    .replace(/[。，·":：、《》]/g, "")
    .replace(/\/\/.*/, "")
    .replace(/[◎〇]/g, "○");

/** lineTransform 带原文偏移映射：transform 后各 UTF-16 单位 → 原文单位偏移。
 *  trim 删首尾、空白串压缩（无 g 标志仅第一处）会使文本与原文不等长，
 *  cpSrcs 溯源编辑器原文所需的换算在此统一维护（lineTransform 即其 text 视图） */
function lineTransformMap(line: string): { text: string; map: number[] } {
  let text = "";
  const map: number[] = [];
  for (let i = 0; i < line.length; i++) {
    text += line[i] === "　" ? "*" : line[i];
    map.push(i);
  }
  let a = 0;
  let b = text.length;
  while (a < b && /\s/.test(text[a])) a++;
  while (b > a && /\s/.test(text[b - 1])) b--;
  text = text.slice(a, b);
  const m = map.slice(a, b);
  const sp = /[ \t]+/.exec(text);
  if (sp) {
    text = text.slice(0, sp.index) + " " + text.slice(sp.index + sp[0].length);
    return {
      text,
      map: [...m.slice(0, sp.index), m[sp.index], ...m.slice(sp.index + sp[0].length)],
    };
  }
  return { text, map: m };
}

const lineTransform = (line: string) => lineTransformMap(line).text;

interface RawChunk {
  from: number;
  to: number;
  text: string;
  chunkText: string;
  lineRanges: Array<[number, number]>;
}

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

/** 全文原始偏移（UTF-16）上的书名区间 */
function locateSpans(text: string): Array<[number, number]> {
  const spans: Array<[number, number]> = [];
  const re = /【[\s\S]*?】/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) spans.push([m.index, m.index + m[0].length]);
  const lastPaired = spans.length ? spans[spans.length - 1][1] : 0;
  const unclosed = text.indexOf("【", lastPaired);
  if (unclosed !== -1) spans.push([unclosed, text.length]);
  return spans;
}

interface LocalRegion {
  from: number;
  to: number;
  kind: "closed" | "opener" | "continuation";
}

function detectRegions(source: string): LocalRegion[] {
  const regions: LocalRegion[] = [];
  const cont = /^[^【】]*】/.exec(source);
  if (cont) regions.push({ from: 0, to: cont[0].length, kind: "continuation" });
  const re = /【[\s\S]*?】|【[^】]*$/g;
  re.lastIndex = cont ? cont[0].length : 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source))) {
    regions.push({
      from: m.index,
      to: m.index + m[0].length,
      kind: m[0].endsWith("】") ? "closed" : "opener",
    });
  }
  const reOrphan = /】/g;
  reOrphan.lastIndex = cont ? cont[0].length : 0;
  while ((m = reOrphan.exec(source))) {
    if (!regions.some((r) => m!.index >= r.from && m!.index < r.to)) {
      regions.push({ from: m.index, to: m.index + 1, kind: "continuation" });
    }
  }
  return regions.sort((a, b) => a.from - b.from);
}

const cpLen = (s: string) => [...s].length;

/** .gj → IR v3 */
export function gj2ir(text: string): IRDocument {
  const { chunks, pageOf } = walkChunks(text);
  const spans = locateSpans(text);
  const pages: IRPage[] = [];
  const overlays: IROverlay[] = [];
  const bookBySpan = new Map<string, IRBookOverlay>();
  const spanKey = (s: [number, number]) => `${s[0]}:${s[1]}`;

  for (const c of chunks) {
    const pageM = /^@(\d+)$/.exec(c.chunkText);
    if (pageM) {
      pages.push({
        id: `p${pageM[1].padStart(4, "0")}`,
        no: Number(pageM[1]),
        src: [c.from, c.to],
        bands: [],
      });
      continue;
    }
    const pageNo = pageOf.get(c) ?? 0;
    if (pageNo === 0 || pages.length === 0) continue;
    const page = pages[pages.length - 1];
    const bandId = `${page.id}-b${page.bands.length}`;
    const band: IRBand = { id: bandId, ord: page.bands.length, src: [c.from, c.to], lines: [] };

    if (isBlankBand(c.text)) {
      band.lines.push({ id: `${bandId}-l0`, ord: 0, src: c.lineRanges[0], elements: [] });
      page.bands.push(band);
      continue;
    }

    const regions = detectRegions(c.text);
    let regionIndex = 0;
    let seg = 0;
    const nextId = () => `${bandId}-e${seg++}`;
    // 区域 → 各行的码点区间（{line, startCp, text}）；骨架中区域字符并入相邻小字段
    const regionRuns = new Map<number, Array<{ line: IRLine; startCp: number; text: string }>>();
    const circleTargets: string[] = [];

    let base = 0;
    c.lineRanges.forEach(([r0, r1], li) => {
      // 重算行变换取原文映射（cpSrcs 溯源用）；与 c.text 各行逐字节一致（同一纯函数）
      const { text: lineSource, map } = lineTransformMap(text.slice(r0, r1));
      const srcAt = (t: number) => r0 + map[t];
      const elements: IRElement[] = [];
      let plainBuf = "";
      let cp = 0; // 行文本码点游标
      const cpSrcs: number[] = [];
      const runsThisLine: Array<{ ri: number; startCp: number; text: string }> = [];

      const flushPlain = () => {
        if (plainBuf.length > 0) {
          elements.push({ id: nextId(), class: "small", text: plainBuf });
          plainBuf = "";
        }
      };

      for (const token of scanInline(lineSource).tokens) {
        if (token.kind === "comment") break;
        if (token.kind !== "text" && token.kind !== "circle") continue;
        const pos = base + token.from;
        while (regionIndex < regions.length && regions[regionIndex].to <= pos) regionIndex++;
        const region = regions[regionIndex]?.from <= pos ? regions[regionIndex] : undefined;
        if (region) {
          const ri = regionIndex;
          let run = runsThisLine.find((r) => r.ri === ri);
          if (!run) { run = { ri, startCp: cp, text: "" }; runsThisLine.push(run); }
          run.text += token.text;
        }
        if (token.size === "large") {
          flushPlain();
          const el: IRElement = { id: nextId(), class: "large", text: token.text,
            ...(cpLen(token.text) > 1 ? { ligature: true } : {}) };
          elements.push(el);
          if (token.kind === "circle") circleTargets.push(el.id);
        } else plainBuf += token.text;
        for (const _ch of token.text) cpSrcs.push(srcAt(token.contentFrom));
        cp += cpLen(token.text);
      }
      flushPlain();

      const line: IRLine = {
        id: `${bandId}-l${li}`,
        ord: li,
        src: c.lineRanges[li],
        elements,
        ...(cpSrcs.length > 0 ? { cpSrcs } : {}),
      };
      band.lines.push(line);
      for (const run of runsThisLine) {
        if (run.text.length === 0) continue;
        const recs = regionRuns.get(run.ri) ?? [];
        recs.push({ line, startCp: run.startCp, text: run.text });
        regionRuns.set(run.ri, recs);
      }
      base += lineSource.length + 1;
    });

    // 圆圈 overlay
    for (const target of circleTargets) overlays.push({ id: `o${overlays.length}`, kind: "circle", target });

    // 书名 overlay 装配（同 span 的开启/延续合并为单一 overlay；span=行级码点区间）
    const [b0, b1] = band.src!;
    const openSpans = spans.filter(([s0]) => s0 >= b0 && s0 < b1).sort((x, y) => x[0] - y[0]);
    const contSpans = spans.filter(([s0, s1]) => s0 < b0 && s1 > b0).sort((x, y) => x[0] - y[0]);
    const contRegions = regions.filter((r) => r.kind === "continuation");
    const openRegions = regions.filter((r) => r.kind !== "continuation");

    const attach = (region: LocalRegion, span: [number, number] | null, createIfMissing: boolean) => {
      const ri = regions.indexOf(region);
      let overlay: IRBookOverlay | undefined = span ? bookBySpan.get(spanKey(span)) : undefined;
      if (!overlay) {
        if (!createIfMissing) return;
        overlay = { id: `o${overlays.length}`, kind: "book-title", spans: [] };
        // 语义边界（渲染开口依据，不依赖 src）：openedHere = 以【开启（孤立】为 false）；
        // closed = 区域含 】（continuation 必含；opener 仅 closed 形态含——EOF 未闭合 false）
        overlay.openedHere = region.kind !== "continuation";
        overlay.closed = region.kind !== "opener";
        if (span) {
          overlay.src = span;
          bookBySpan.set(spanKey(span), overlay);
        }
        overlays.push(overlay);
      }
      // 挂接已有 overlay 的延续段：区域含 】则书已闭合（创建时的标志只反映
      // 开启区域形态——跨 band wrap 的闭合信息在延续段到达时才补全）
      if (region.kind !== "opener") overlay.closed = true;
      for (const run of regionRuns.get(ri) ?? []) {
        overlay.spans.push({
          line: run.line.id,
          range: [run.startCp, run.startCp + cpLen(run.text)],
        });
      }
    };

    openRegions.forEach((r, k) => attach(r, openSpans[k] ?? null, true));
    contRegions.forEach((r, k) => {
      const span = contSpans[k] ?? null;
      attach(r, span, span === null);
    });

    page.bands.push(band);
  }

  return {
    version: 3,
    meta: {
      sourceFormat: "gj/2",
      generatedBy: "guji-ir/3-gj2",
      fidelity: "full",
      profile: { stripPunct: [...GUJI_PROFILE.stripPunct], normalize: GUJI_PROFILE.normalize.map(([a, b]) => [a, b]) },
      lineLayout: "fold",
      orientation: "vertical-rtl",
      rangeUnit: "codepoint",
      srcUnit: "utf-16",
    },
    pages,
    overlays,
  };
}
