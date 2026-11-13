// Guji IR v2：.gj 等输入 → 语义结构 JSON → 竖排刻本渲染 / OCR 版式分析。
// 设计见 docs/design/guji-ir.md。相对 v1 的结构升级：
// - 物理层级显式：页 → 大行（band）→ 小行（line，= .gj 内一条物理折行；
//   换行是一等公民，不再以 br 段标记）；行带 id + 源偏移，行级 GT 可寻址
// - 元素双轴：class（大字/小字，版式事实）× sem（heading/head/gloss/title/mark，
//   逻辑事实）正交，OCR 版式任务常只需前者
// - 跨行语义 overlay：书名等跨行元素登记在页级 semantics，spans 精确到
//   （行 id， 行内字符区间）；行内以 sem=title 的锚元素占位（自带片段文本，
//   忽略 overlay 亦可渲染）
// 保真：text 保留标点/空格；清洗口径在 meta.profile（渲染/评测同源）。

/** 清洗口径：渲染与评测共用（写入 IR meta，eval_cer.py 读同一定义） */
export interface IRProfile {
  /** 渲染/评测时从 text 段剔除的标点（与原 split-line.ts 剔除集一致） */
  stripPunct: string[];
  /** 形近归一（如 ◎/〇 → ○，原 split 行为） */
  normalize: Array<[string, string]>;
}

export const GUJI_PROFILE: IRProfile = {
  stripPunct: [..."。，·\":：、《》"],
  normalize: [
    ["◎", "○"],
    ["〇", "○"],
  ],
};

export interface IRMeta {
  sourceFormat: string; // gj | crawl-draft | …
  generatedBy: string;
  fidelity: "full";
  profile: IRProfile;
  /** 小行切分来源：fold = 转写折行（保真）；未来自动版式切分需另立来源标记 */
  lineLayout: "fold";
  /** 版面方向：列内自上而下、列间自右而左（row-reverse 语义） */
  orientation: "vertical-rtl";
}

export type SizeClass = "large" | "small"; // 大字 2×2 字格 / 小字 1×1
export type SemKind = "heading" | "head" | "gloss" | "title" | "mark";

export interface IRElement {
  id: string;
  class: SizeClass;
  sem: SemKind;
  /** 保真文本（title = 本行内的书名片段，不含【】） */
  text: string;
  style?: "circled"; // mark 的带圈形态
  /** sem=title：指向 page.semantics.books[].id */
  ref?: string;
}

/** 小行（.gj 内一条物理折行；换行的结构化表达） */
export interface IRLine {
  id: string; // p0312-b3-l0
  ord: number;
  /** 原始文本中该物理行区间（含行尾换行前） */
  src?: [number, number];
  elements: IRElement[];
}

export interface IRBand {
  id: string; // p0312-b3
  ord: number;
  /** 标题大行（#/##/###）：1/2/3 级（书名/集名/部首）。标题不物化为小行
   *  （band.heading 即其全部内容，行级消费方可据此合成单行） */
  heading?: { level: 1 | 2 | 3; text: string };
  src?: [number, number];
  lines: IRLine[];
}

/** 跨行书名：单语义元素；spans 按行引用，range 为该行规范文本（各元素
 *  text 依序拼接）内的字符区间。孤立 】（无开启【）也登记（无 src）。 */
export interface IRBookSpan {
  line: string; // 目标行 id
  range: [number, number];
}

export interface IRBook {
  id: string; // p0312-bk0
  /** 原始文本区间（含【】）；孤立 】 无 src */
  src?: [number, number];
  spans: IRBookSpan[];
}

export interface IRPage {
  id: string; // p0312
  no: number;
  src?: [number, number];
  bands: IRBand[];
  semantics: { books: IRBook[] };
}

export interface IRDocument {
  version: 2;
  meta: IRMeta;
  pages: IRPage[];
}

/** 行规范文本（各元素 text 依序拼接；书名 range 的坐标系） */
export function lineText(line: { elements: IRElement[] }): string {
  return line.elements.map((e) => e.text).join("");
}

// ---- 渲染联动（沿用 v1 接口；数据源改为 v2 的行/书名 overlay） ----

export const bandKey = (page: number, index: number) => `${page}:${index}`;

/** 书名区间对应的各大行内 item 序号段 */
export interface BookRuns {
  [bandKeyStr: string]: Array<{ start: number; count: number }>;
}

/** 渲染联动高亮：光标所在大行 + 书名区间对应的各大行序号段 */
export interface RenderHighlight {
  band: { page: number; index: number } | null;
  book: BookRuns | null;
}
