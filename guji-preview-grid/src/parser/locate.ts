// 带源偏移的定位器：光标偏移 ↔ (页, 大行)，及书名区间。
// 不改动解析器（其行为被 fixtures 锁定）；本模块独立复刻 split-line.ts 的
// 分块语义并保留偏移，用对等性测试（test/locate.spec.ts）防止漂移：
// 定位器产出的块文本序列必须逐个等于 split() 的输出。

/** 一个大行（band）：源区间 + 归属页与页内序号（对应 PageModel.l 下标） */
export interface BandInfo {
  page: number;
  index: number;
  from: number; // 源文本起始偏移（该行行首）
  to: number;   // 结束偏移（不含随后的空行）
  /** 与 split() 输出逐字符一致的块文本（用于对等性测试与诊断） */
  chunkText: string;
}

/** 页声明块（@N 独占一块，本身不是大行） */
export interface PageChunk {
  page: number;
  from: number;
  to: number;
}

/** 书名区间：从【到】（或到文末的未闭合区间） */
export interface BookSpan {
  from: number;
  to: number;
}

export interface Located {
  bands: BandInfo[];
  pages: PageChunk[];
}

/** 与 split() 一致的块级变换（判存活与文本对等用） */
const chunkTransform = (s: string) =>
  s
    .trim()
    .replace(/[。，·":：、《》]/g, "")
    .replace(/\/\/.*/, "")
    .replace(/[◎〇]/g, "○");

const lineTransform = (line: string) =>
  line.replace(/　/g, "*").trim().replace(/[ \t]+/, " ");

/** 定位全部页块与大行。 */
export function locate(text: string): Located {
  // 1) 丢弃「== 分隔条及之前全部内容」（与 split 一致：贪婪到最后一个 ==，止于该行行尾）
  let liveStart = 0;
  const cut = /[\s\S]*==.*/.exec(text);
  if (cut) {
    liveStart = cut.index + cut[0].length;
    if (text[liveStart] === "\n") liveStart += 1;
  }

  const bands: BandInfo[] = [];
  const pages: PageChunk[] = [];
  let page = 0; // 尚无 @N 声明时内容不属任何页（parsePages 也会丢弃）
  let index = 0;
  let chunkFrom = -1;
  let chunkTo = 0;
  let chunkLines: string[] = []; // 逐行变换后的文本（与 split 的行级变换一致）
  let started = false;

  const flush = () => {
    if (!started) return;
    // 与 split 一致：行级变换后 join，再做块级变换（trim/去标点/去注释/归一）
    const chunkText = chunkTransform(chunkLines.join("\n"));
    if (chunkText.length > 0) {
      const m = /^@(\d+)$/.exec(chunkText);
      if (m) {
        page = Number(m[1]);
        index = 0;
        pages.push({ page, from: chunkFrom, to: chunkTo });
      } else {
        bands.push({ page, index: index++, from: chunkFrom, to: chunkTo, chunkText });
        // page=0 的内容在 parsePages 中被丢弃，这里仍记录（index 从 0 计），
        // 调用方用 page>0 过滤
      }
    }
    started = false;
    chunkLines = [];
  };

  // 2) 逐行走原文（含 \n 偏移），行变换后为空即块边界
  let lineStart = liveStart;
  for (let i = liveStart; i <= text.length; i++) {
    if (i === text.length || text[i] === "\n") {
      const line = text.slice(lineStart, i);
      const t = lineTransform(line);
      if (t === "") {
        flush(); // 块结束于最后一个内容行行尾（不含空行）
      } else {
        if (!started) {
          started = true;
          chunkFrom = lineStart;
        }
        chunkTo = i;
        chunkLines.push(t);
      }
      lineStart = i + 1;
    }
  }
  flush();
  return { bands, pages };
}

/** 光标偏移 → 所在大行；间隙（空行/页声明块/文件头）取前一个大行（行尾输入的自然延续） */
export function bandAt(loc: Located, offset: number): BandInfo | null {
  for (const p of loc.pages) {
    if (offset >= p.from && offset <= p.to) return null; // 页声明行上不高亮
  }
  let prev: BandInfo | null = null;
  for (const b of loc.bands) {
    if (offset < b.from) break;
    if (offset <= b.to) return b.page > 0 ? b : null;
    prev = b;
  }
  return prev && prev.page > 0 ? prev : null;
}

/** 大行的首个非空白字符偏移（点击渲染行 → 编辑器光标落点） */
export function bandStartOffset(band: BandInfo, text: string): number {
  const lead = /^\s*/.exec(text.slice(band.from, band.to));
  return band.from + (lead ? lead[0].length : 0);
}

/** 全文书名区间（【…】 惰性配对；未闭合的【到文末） */
export function locateBooks(text: string): BookSpan[] {
  const spans: BookSpan[] = [];
  const re = /\【[\s\S]*?\】/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) spans.push({ from: m.index, to: m.index + m[0].length });
  // 未闭合：【 在已配对区间之外的最后一个
  const lastPairedOpen = spans.length ? spans[spans.length - 1].from : -1;
  const rest = text.slice(lastPairedOpen + 1);
  const unclosed = rest.lastIndexOf("【");
  if (unclosed !== -1) spans.push({ from: lastPairedOpen + 1 + unclosed, to: text.length });
  return spans;
}

export function spanAt(spans: BookSpan[], offset: number): BookSpan | null {
  for (const s of spans) {
    if (offset >= s.from && offset <= s.to) return s;
  }
  return null;
}

/** 书名区间的 bandKey → 高亮序号段（同一视图对矩阵 item 与 flex 片段通用：
 *  每条占用的 item/片段数 = 区间在该大行内的换行数 + 1） */
export interface BookRuns {
  [bandKey: string]: Array<{ start: number; count: number }>;
}

export const bandKey = (page: number, index: number) => `${page}:${index}`;

/** 渲染联动高亮：光标所在大行 + 书名区间对应的各大行序号段 */
export interface RenderHighlight {
  band: { page: number; index: number } | null;
  book: BookRuns | null;
}

/** 光标所在书名区间 → 各大行内需高亮的 item 序号段 */
export function bookRuns(
  loc: Located,
  spans: BookSpan[],
  span: BookSpan | null,
  text: string,
): BookRuns | null {
  if (!span) return null;
  const runs: BookRuns = {};
  for (const b of loc.bands) {
    if (b.to <= span.from || b.from >= span.to) continue; // 与区间无交
    const overlapFrom = Math.max(b.from, span.from);
    const overlapTo = Math.min(b.to, span.to);
    const newlines = text.slice(overlapFrom, overlapTo).split("\n").length - 1;
    const count = newlines + 1;
    // 起始序号：区间起点在本行内 → 本行内更早的【 开区间数；否则为延续段（前导，
    // 序号 0——延续片段是该行的首个书名块）
    let start = 0;
    if (span.from >= b.from && span.from < b.to) {
      start = spans.filter((s) => s !== span && s.from >= b.from && s.from < span.from).length;
    }
    (runs[bandKey(b.page, b.index)] ??= []).push({ start, count });
  }
  return Object.keys(runs).length ? runs : null;
}

/** 诊断辅助：块文本序列（页块 + 大行块，按位置序），应与 split(text) 逐个相等 */
export function parityChunks(text: string): string[] {
  const loc = locate(text);
  return [
    ...loc.pages.map((p) => {
      const raw = text.slice(p.from, p.to);
      return { from: p.from, s: raw.split("\n").map(lineTransform).join("\n") };
    }),
    ...loc.bands.map((b) => ({ from: b.from, s: b.chunkText })),
  ]
    .sort((a, b) => a.from - b.from)
    .map((c) => chunkTransform(c.s));
}
