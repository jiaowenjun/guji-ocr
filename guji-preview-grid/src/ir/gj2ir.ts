// .gj 文本 → Guji IR v3（骨架 + overlay 双层）。
// 骨架：页→大行→小行→元素（大字/小字/合字）；标题物化为逐字大字；换行=行结构。
// overlay（文档级）：circle（圆圈，target=元素）、book-title（书名，spans=行+码点
// 区间；同一原始 span 的开启/延续区域合并为单一 overlay）。
// 骨架不依赖 overlay：去掉全部 overlay 后占格与换行不变（验收契约见 ir.spec）。
// 词法镜像 parse-inline 状态机（消费 lineTransform 后文本；#( 双前瞻按 code unit；
// 行内 // 截断）。src 为 UTF-16 仅溯源；行内 range 为码点半开区间。
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

const isOrdinary = (c: string) => !"#【】\n".includes(c);

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

    const headingM = /^(#+) (.*)$/.exec(c.text.trim());
    if (headingM && !c.text.trim().includes("\n")) {
      // 标题入骨架：逐字大字元素；层级为元数据
      band.level = Math.min(3, headingM[1].length) as 1 | 2 | 3;
      const seg = 0;
      band.lines.push({
        id: `${bandId}-l0`,
        ord: 0,
        src: c.lineRanges[0],
        elements: [...headingM[2]].map((ch) => ({
          id: `${bandId}-e${seg}`,
          class: "large" as const,
          text: ch,
        })),
      });
      page.bands.push(band);
      continue;
    }

    const regions = detectRegions(c.text);
    let seg = 0;
    const nextId = () => `${bandId}-e${seg++}`;
    // 区域 → 各行的码点区间（{line, startCp, text}）；骨架中区域字符并入相邻小字段
    const regionRuns = new Map<number, Array<{ line: IRLine; startCp: number; text: string }>>();
    const circleTargets: string[] = [];

    const lineSources = c.text.split("\n");
    let base = 0;
    lineSources.forEach((lineSource, li) => {
      const elements: IRElement[] = [];
      let plainBuf = "";
      let cp = 0; // 行文本码点游标
      const runsThisLine: Array<{ ri: number; startCp: number; text: string }> = [];

      const flushPlain = () => {
        if (plainBuf.length > 0) {
          elements.push({ id: nextId(), class: "small", text: plainBuf });
          plainBuf = "";
        }
      };

      let i = 0;
      while (i < lineSource.length) {
        const pos = base + i;
        const region = regions.find((r) => pos >= r.from && pos < r.to);
        const ch = lineSource[i];

        if (region) {
          // 书名字符并入当前小字段（骨架括号无关）；区间按码点游标记录
          const cpNow = lineSource.codePointAt(i)!;
          const chu = String.fromCodePoint(cpNow);
          const mapped = chu === "【" || chu === "】" ? null : chu === "*" ? " " : chu;
          const ri = regions.indexOf(region);
          let run = runsThisLine.find((r) => r.ri === ri);
          if (!run) {
            run = { ri, startCp: cp, text: "" };
            runsThisLine.push(run);
          }
          if (mapped !== null) {
            plainBuf += mapped;
            run.text += mapped;
            cp += 1;
          }
          i += chu.length;
          continue;
        }

        if (ch === "/" && lineSource[i + 1] === "/") break; // 行内注释截断
        if (ch === "#") {
          flushPlain();
          const n1 = lineSource[i + 1];
          if (n1 === "(") {
            // 带圈：大字/合字进骨架，圆圈进 overlay
            let j = i + 2;
            let inner = "";
            if (lineSource[j + 1] === ")" || lineSource[j + 2] === ")") {
              while (j < lineSource.length && lineSource[j] !== ")" && isOrdinary(lineSource[j])) {
                inner += lineSource[j] === "*" ? " " : lineSource[j];
                j++;
              }
              if (lineSource[j] === ")") j++;
            } else if (j < lineSource.length && isOrdinary(lineSource[j])) {
              inner = lineSource[j] === "*" ? " " : lineSource[j];
              j++;
            } else {
              j = i + 2;
            }
            if (inner) {
              const el: IRElement = {
                id: nextId(),
                class: "large",
                text: inner,
                ...(cpLen(inner) > 1 ? { ligature: true } : {}),
              };
              elements.push(el);
              circleTargets.push(el.id);
              cp += cpLen(inner);
            }
            i = j;
            continue;
          }
          const cpRaw = lineSource.codePointAt(i + 1);
          const hc = cpRaw !== undefined ? String.fromCodePoint(cpRaw) : undefined;
          if (hc !== undefined && isOrdinary(hc)) {
            const text = hc === "*" ? " " : hc;
            elements.push({ id: nextId(), class: "large", text });
            cp += 1;
            i += 1 + hc.length;
            continue;
          }
          i++;
          continue;
        }

        const cpNow = lineSource.codePointAt(i)!;
        const chu = String.fromCodePoint(cpNow);
        plainBuf += chu === "*" ? " " : chu;
        cp += 1;
        i += chu.length;
      }
      flushPlain();

      const line: IRLine = {
        id: `${bandId}-l${li}`,
        ord: li,
        src: c.lineRanges[li],
        elements,
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
      sourceFormat: "gj",
      generatedBy: "guji-ir/3",
      fidelity: "full",
      profile: GUJI_PROFILE,
      lineLayout: "fold",
      orientation: "vertical-rtl",
      rangeUnit: "codepoint",
      srcUnit: "utf-16",
    },
    pages,
    overlays,
  };
}
