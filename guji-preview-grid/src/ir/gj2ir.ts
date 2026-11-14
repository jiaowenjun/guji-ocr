// .gj 文本 → Guji IR v3（骨架 + overlay 双层）。
// 骨架：页→大行→小行→元素（大字/小字/合字）；标题物化为逐字大字；换行=行结构。
// overlay（文档级）：circle（圆圈，target=元素）、book-title（书名，spans=行+码点
// 区间；同一原始 span 的开启/延续区域合并为单一 overlay）。
// 骨架不依赖 overlay：去掉全部 overlay 后占格与换行不变（验收契约见 ir.spec）。
// 词法镜像 parse-inline 状态机（消费 lineTransform 后文本；#( 双前瞻按 code unit；
// 行内 // 截断）。src 为 UTF-16 仅溯源；行内 range 为码点半开区间。
// 字头簇糖（2026-11-14，语法单一事实源在 parser/split-line.ts 扫描器）：
//   - 带圈续写 #(五)(增)𠂂 ≡ #(五)#(增)#𠂂（( 紧随大字 token 即续写带圈）
//   - 裸字大写：带圈 token 后一字=字头；「古文」标记或 、 后=变体（连串）
//   - #(三)丹，古文：𠁿㣋 ≡ #(三)#丹古文#𠁿#㣋（，：两侧可省；为小字内容，
//     TXT 经 profile 剔除与长式一致）
//   - 普通 #X 后不裸写；状态不跨行；行首承接「古文：」须带冒号（正文不误判）
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
import { isBareLargeChar } from "../parser/split-line";

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

const isOrdinary = (c: string) => !"#【】\n".includes(c);

const DIGIT_CN = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"];
function numberToCn(num: number): string | null {
  if (num < 0 || num > 99) return null;
  if (num < 10) return DIGIT_CN[num];
  const tens = Math.floor(num / 10);
  const ones = num % 10;
  if (num < 20) return "十" + (ones ? DIGIT_CN[ones] : "");
  return DIGIT_CN[tens] + "十" + (ones ? DIGIT_CN[ones] : "");
}
/** 带圈内容速记归一：z/Z→增；数字→汉字（1→一、15→十五） */
function normalizeShorthand(inner: string): string {
  return inner
    .replace(/z/gi, "增")
    .replace(/\d+/g, (d) => numberToCn(Number(d)) ?? d);
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

    const headingM = /^(#+) (.*)$/.exec(c.text.trim());
    if (headingM && !c.text.trim().includes("\n")) {
      // 标题入骨架：逐字大字元素；层级为元数据。
      // 单行 band 的 c.text.trim() 即变换后行文本——标题字偏移经映射回原文记 cpSrcs
      band.level = Math.min(3, headingM[1].length) as 1 | 2 | 3;
      const [h0, h1] = c.lineRanges[0];
      const { map: headMap } = lineTransformMap(text.slice(h0, h1));
      let u = headingM[1].length + 1;
      const cpSrcs: number[] = [];
      band.lines.push({
        id: `${bandId}-l0`,
        ord: 0,
        src: c.lineRanges[0],
        elements: [...headingM[2]].map((ch, k) => {
          cpSrcs.push(h0 + headMap[u]);
          u += ch.length;
          return { id: `${bandId}-e${k}`, class: "large" as const, text: ch };
        }),
        cpSrcs,
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

      // 字头簇糖状态（行内局部，不跨行）：lastLargeKind=上一元素的大字来源；
      // variantMode=古文标记或 、 之后（裸字=异体变体）。书名区/普通小字退出
      let lastLargeKind: "circled" | "plain" | "bare" | null = null;
      let variantMode = false;

      const flushPlain = () => {
        if (plainBuf.length > 0) {
          elements.push({ id: nextId(), class: "small", text: plainBuf });
          plainBuf = "";
        }
      };

      // 带圈 token 解析（lead=前导语法字符数：#=1、糖续写=0）。扩展输入（原文不动，
      // src 对齐保持）：全角括号等同半角；括号内速记 z→增、数字→汉字（1→一等）
      const parseCircled = (openAt: number, lead: number): number => {
        const innerStart = openAt + 1 + lead;
        let j = innerStart;
        let inner = "";
        const isCloser = (c: string) => c === ")" || c === "）";
        const isInner = (c: string) => isOrdinary(c) && c !== "（" && c !== "）";
        if (isCloser(lineSource[j + 1]) || isCloser(lineSource[j + 2])) {
          while (j < lineSource.length && !isCloser(lineSource[j]) && isInner(lineSource[j])) {
            inner += lineSource[j] === "*" ? " " : lineSource[j];
            j++;
          }
          if (isCloser(lineSource[j])) j++;
        } else if (j < lineSource.length && isInner(lineSource[j])) {
          inner = lineSource[j] === "*" ? " " : lineSource[j];
          j++;
        } else {
          j = innerStart;
        }
        inner = normalizeShorthand(inner);
        if (inner) {
          const el: IRElement = {
            id: nextId(),
            class: "large",
            text: inner,
            ...(cpLen(inner) > 1 ? { ligature: true } : {}),
          };
          elements.push(el);
          circleTargets.push(el.id);
          // 合字/速记（z→增 等）文本与源不 1:1，各字统一记 token 内文起点
          for (let q = 0; q < cpLen(inner); q++) cpSrcs.push(srcAt(innerStart));
          cp += cpLen(inner);
        }
        return j;
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
            cpSrcs.push(srcAt(i));
            cp += 1;
          }
          i += chu.length;
          lastLargeKind = null;
          variantMode = false;
          continue;
        }

        if (ch === "/" && lineSource[i + 1] === "/") break; // 行内注释截断
        if (ch === "#") {
          flushPlain();
          const n1 = lineSource[i + 1];
          if (n1 === "(" || n1 === "（") {
            i = parseCircled(i, 1);
            lastLargeKind = "circled";
            continue;
          }
          const cpRaw = lineSource.codePointAt(i + 1);
          const hc = cpRaw !== undefined ? String.fromCodePoint(cpRaw) : undefined;
          if (hc !== undefined && isOrdinary(hc)) {
            const text = hc === "*" ? " " : hc;
            elements.push({ id: nextId(), class: "large", text });
            cpSrcs.push(srcAt(i + 1));
            cp += 1;
            i += 1 + hc.length;
            lastLargeKind = "plain";
            continue;
          }
          i++;
          lastLargeKind = null;
          continue;
        }

        // 糖：带圈续写——( 紧随大字 token 即 #( 的省 # 形
        if ((ch === "(" || ch === "（") && lastLargeKind) {
          flushPlain();
          i = parseCircled(i, 0);
          lastLargeKind = "circled";
          continue;
        }

        // 糖：古文异体标记——大字 token 后紧邻 ，?古文：?（行首承接形须带冒号，
        // 与正文「古文酉」区分）；标记本身为小字内容，其后裸字=变体
        if ((lastLargeKind && (ch === "古" || ch === "，")) || (i === 0 && ch === "古")) {
          const mm = (
            i === 0 && !lastLargeKind ? /^古文[:：]/ : /^，?古文[:：]?/
          ).exec(lineSource.slice(i));
          if (mm) {
            for (const mc of mm[0]) {
              plainBuf += mc;
              cpSrcs.push(srcAt(i));
              cp += 1;
              i += 1;
            }
            variantMode = true;
            lastLargeKind = null;
            continue;
          }
        }

        const cpNow = lineSource.codePointAt(i)!;
        const chu = String.fromCodePoint(cpNow);

        // 糖：裸字大写——任意大字 token 后（字头连写串，#丶#宔 ≡ #丶宔）或
        // 标记/、 后（变体，连串）。「古」排除：是「古文」标记首字/跨行半个
        // 标记（#下古↵文#丅），不参与裸写
        if (isBareLargeChar(chu) && (variantMode || (lastLargeKind !== null && chu !== "古"))) {
          flushPlain();
          elements.push({ id: nextId(), class: "large", text: chu });
          cpSrcs.push(srcAt(i));
          cp += 1;
          lastLargeKind = "bare";
          i += chu.length;
          continue;
        }

        plainBuf += chu === "*" ? " " : chu;
        cpSrcs.push(srcAt(i));
        cp += 1;
        // 、 紧随大字/变体链 → 并列变体语境（裸字连写继续）；其余小字退出
        if (chu === "、" && (lastLargeKind || variantMode)) variantMode = true;
        else variantMode = false;
        lastLargeKind = null;
        i += chu.length;
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
