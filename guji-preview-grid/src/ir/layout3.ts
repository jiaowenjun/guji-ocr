// 布局引擎 v3：IR v3 骨架 → 字格坐标布局（主路径第一段，不依赖任何 overlay）。
// 几何语义沿用矩阵引擎：复合大行的段流 [前置小字组] (大字+可选小字组)* [尾随小字组]；
// 小字组每小行一列（小行 0 在最右，row-reverse 语义），组内居中取整；大字恒在
// 局部列 0-1；大字占 2×2，合字 n 字合占一个 2×2，小字每字 1×1。
// 渲染口径：占格与行数按 profile 清洗后计（标点剔除、◎〇→○——骨架保真保留
// 标点，清洗属展示规则）；书名 overlay 定位用与 cells 平行的原文码点偏移
// （rawOffsets），坐标仍指向未清洗的行规范文本。
// 与旧引擎的差别：书名/圆圈不再参与布局（overlay 在渲染期装饰）；书名不会吞换行。
import type { IRBand, IRDocument } from "./types";
import { GUJI_PROFILE } from "./types";

export interface L3Item {
  kind: "large" | "run";
  r: number; // band 局部行（cell 单位）
  c: number; // band 局部列
  /** large：单字或合字串 */
  text?: string;
  ligature?: boolean;
  /** large：元素 id（circle overlay 定位） */
  elId?: string;
  /** run：逐字（profile 清洗后——标点剔除、◎〇→○） */
  cells?: string[];
  /** run：与 cells 平行——各字在行规范文本（未清洗）中的码点偏移（book overlay 定位） */
  rawOffsets?: number[];
  /** run：来源小行 id（book overlay 定位） */
  lineId?: string;
  /** run：首字符在该行规范文本（未清洗）中的码点偏移 */
  cpStart?: number;
  /** run：奇数余量组的亚格居中（cols−k 为奇数时整组右移 0.5 字格，
   *  复刻 flex auto-margin 的精确居中——如 2 列大行内的单列「古文」组） */
  halfShift?: 0.5;
}

export interface L3Band {
  id: string;
  cols: number;
  rows: number;
  items: L3Item[];
}

/** 版面每列字格数上限（武英殿刻本物理版框；29 页金标实测均 24）。
 *  仅渲染层封顶裁剪（展示规则），layout3 骨架保真不裁——超长列是转写
 *  与物理版面不符的错误信号，由渲染层挂警示条暴露 */
export const PAGE_ROW_CAP = 24;

export interface L3Page {
  no: number;
  rows: number;
  totalCols: number;
  bands: L3Band[];
  /** band i 的页级起始列（band 0 在最右；colStart[i] = 其右侧各 band 列数之和） */
  colStarts: number[];
}

const cpLen = (s: string) => [...s].length;

/** 单字清洗：标点剔除、形近归一；被剔除返回 null */
const cleanChar = (ch: string): string | null => {
  let out = ch;
  for (const [from, to] of GUJI_PROFILE.normalize) out = out.split(from).join(to);
  return GUJI_PROFILE.stripPunct.includes(out) ? null : out;
};

/** 文本 → 清洗后逐字 + 各字在原文中的码点偏移 */
function cleanedChars(text: string): { cleaned: string[]; offsets: number[] } {
  const cleaned: string[] = [];
  const offsets: number[] = [];
  let cp = 0;
  for (const ch of text) {
    const c = cleanChar(ch);
    if (c !== null) {
      cleaned.push(c);
      offsets.push(cp);
    }
    cp += 1;
  }
  return { cleaned, offsets };
}

interface SmallLine {
  lineId: string;
  cpStart: number;
  cleaned: string[];
  offsets: number[];
}

/** 复合大行：段流切分 + 占格（镜像旧 parseLineBlocks 分组，但按行/元素而非块） */
function layoutComposite(band: IRBand): L3Band {
  const items: L3Item[] = [];
  const groups: Array<{ r: number; lines: SmallLine[] }> = [];
  let curFrag: SmallLine | null = null;
  let group: SmallLine[] = [];
  let r = 0;

  const flushFrag = () => {
    if (curFrag) {
      if (curFrag.cleaned.length > 0) group.push(curFrag);
      curFrag = null;
    }
  };
  const flushGroup = () => {
    flushFrag();
    if (group.length > 0) {
      groups.push({ r, lines: group });
      r += Math.max(...group.map((l) => l.cleaned.length));
      group = [];
    }
  };

  for (const line of band.lines) {
    let cp = 0;
    for (const el of line.elements) {
      if (el.class === "small") {
        // 小字：按元素清洗合并（cpStart 取行内原文偏移）
        const { cleaned, offsets } = cleanedChars(el.text);
        if (!curFrag) curFrag = { lineId: line.id, cpStart: cp, cleaned: [], offsets: [] };
        curFrag.cleaned.push(...cleaned);
        curFrag.offsets.push(...offsets.map((o) => o + cp));
      } else {
        flushGroup();
        items.push({
          kind: "large",
          r,
          c: 0,
          text: el.text,
          ligature: el.ligature,
          elId: el.id,
        });
        r += 2; // 大字/合字恒占一个 2×2 格
      }
      cp += cpLen(el.text);
    }
    flushFrag(); // 行边界 = 小行边界（书名不会吞换行）
  }
  flushGroup();

  const cols = Math.max(2, ...groups.map((g) => g.lines.length));
  for (const g of groups) {
    const k = g.lines.length;
    const slack = cols - k;
    const start = Math.floor(slack / 2);
    const half = slack % 2 === 1 ? (0.5 as const) : undefined; // 亚格居中
    g.lines.forEach((l, j) => {
      items.push({
        kind: "run",
        r: g.r,
        c: start + (k - 1 - j), // 小行 0 在最右
        cells: l.cleaned,
        rawOffsets: l.offsets,
        lineId: l.lineId,
        cpStart: l.cpStart,
        halfShift: half,
      });
    });
  }
  return { id: band.id, cols, rows: r, items };
}

function layoutBand(band: IRBand): L3Band {
  if (band.level !== undefined) {
    // 标题大行：逐字 2×2，缩进 = 层级-1（顶部留 indent 个大字位）；标题字同样清洗
    const indent = band.level - 1;
    const chars = (band.lines[0]?.elements ?? []).filter((el) => cleanChar(el.text) !== null);
    const items = chars.map((el, idx) => ({
      kind: "large" as const,
      r: 2 * (indent + idx),
      c: 0,
      text: el.text,
      elId: el.id,
    }));
    return { id: band.id, cols: 2, rows: 2 * (indent + chars.length), items };
  }
  return layoutComposite(band);
}

export function layout3(doc: IRDocument): L3Page[] {
  return doc.pages.map((page) => {
    const bands = page.bands.map(layoutBand);
    const rows = Math.max(2, ...bands.map((b) => b.rows));
    const colStarts: number[] = [];
    let acc = 0;
    for (let i = bands.length - 1; i >= 0; i--) {
      colStarts[i] = acc;
      acc += bands[i].cols;
    }
    return { no: page.no, rows, totalCols: Math.max(2, acc), bands, colStarts };
  });
}
