// Guji IR v3：双层结构（允许破坏性更新，替换 v2 内部模型）。
// 设计见 docs/design/guji-ir.md §7。核心原则：
//   骨架决定文本、占格与换行；overlay 描述附着其上的样式或语义。
//   去掉全部 overlay 后，页面仍具有相同的阅读顺序、字格占用与行边界。
//
// 骨架（排版版式）：页 → 大行 → 小行 → 元素
//   - 大字元素：恰好占一个大字格（2×2）；合字 ligature:true 时 n 个文本字符合占
//     一个大字格（如 #(十一)）——合字是骨架事实，与圆圈样式无关
//   - 小字元素：每字符占一个小字格（1×1）
//   - 小行 = .gj 内一条物理折行（换行是一等结构；meta.lineLayout 声明来源）
//   - 标题文字同样物化进骨架（逐字大字元素），层级 level 仅为元数据
// overlay（文档级，单向引用骨架）：
//   - circle：圆圈样式，target 指向元素 id（修饰该元素的字格）
//   - book-title：书名样式/语义，spans 按（行 id，行内码点半开区间）引用；
//     跨行/跨页书名为单一 overlay；骨架中不存在书名锚元素
//
// 单位约定：行内 range 一律 Unicode 码点半开区间（禁止切开组合字形/代理对）；
// 源码 src 偏移一律 UTF-16 码元（仅溯源与编辑器联动，渲染不得依赖）。
import type { PageModel } from "../components/flex/model";

/** 清洗口径：渲染与评测共用（写入 IR meta，eval_cer.py 读同一定义） */
export interface IRProfile {
  stripPunct: string[];
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
  sourceFormat: string;
  generatedBy: string;
  fidelity: "full";
  profile: IRProfile;
  /** 小行切分来源：fold = 转写折行（≠ 扫描图检测行，不含坐标） */
  lineLayout: "fold";
  orientation: "vertical-rtl";
  /** 行内 range 的单位（码点，半开区间） */
  rangeUnit: "codepoint";
  /** src 偏移的单位（UTF-16 码元；仅溯源/联动，布局渲染不得依赖） */
  srcUnit: "utf-16";
}

export type SizeClass = "large" | "small";

/** 骨架元素：占格事实。大字恰好一个 2×2 格（合字 n 字合占一格）；小字每字 1×1 */
export interface IRElement {
  id: string;
  class: SizeClass;
  text: string;
  /** 合字：全部文本字符合占一个大字格（仅 large）；与圆圈样式无关 */
  ligature?: boolean;
}

/** 小行（物理折行） */
export interface IRLine {
  id: string; // p0312-b3-l0
  ord: number;
  src?: [number, number]; // UTF-16，原文该行区间
  elements: IRElement[];
}

export interface IRBand {
  id: string; // p0312-b3
  ord: number;
  /** 标题大行层级 1/2/3（#/##/###）——元数据；标题文字已物化进 lines（逐字大字） */
  level?: 1 | 2 | 3;
  src?: [number, number];
  lines: IRLine[];
}

export interface IRPage {
  id: string;
  no: number;
  src?: [number, number];
  bands: IRBand[];
}

export interface IRCircleOverlay {
  id: string;
  kind: "circle";
  /** 被圆圈修饰的大字格（元素 id；应为 large 元素） */
  target: string;
}

export interface IRBookSpan {
  /** 目标小行 id */
  line: string;
  /** 行规范文本（各元素 text 依序拼接）内的码点半开区间 */
  range: [number, number];
}

export interface IRBookOverlay {
  id: string;
  kind: "book-title";
  spans: IRBookSpan[];
  /** 原文区间（UTF-16，含【】）——仅溯源与编辑器联动；无 .gj 源时缺省 */
  src?: [number, number];
  /** 语义边界（渲染开口依据，不依赖 src）：首段是否以【开启（孤立】延续为 false） */
  openedHere?: boolean;
  /** 末段是否已见】闭合（EOF 未闭合为 false——应渲染为开口而非闭合框） */
  closed?: boolean;
}

export type IROverlay = IRCircleOverlay | IRBookOverlay;

export interface IRDocument {
  version: 3;
  meta: IRMeta;
  pages: IRPage[];
  /** 文档级 overlay（跨页书名等直接挂文档，不登记在起始页） */
  overlays: IROverlay[];
}

/** 行规范文本（各元素 text 依序拼接；码点 range 的坐标系） */
export function lineText(line: { elements: IRElement[] }): string {
  return line.elements.map((e) => e.text).join("");
}

// ---- 渲染联动接口（v3：书名高亮按 overlay id，由渲染器点亮其全部覆盖矩形） ----

export interface RenderHighlight {
  band: { page: number; index: number } | null;
  /** 光标所在书名 overlay id（null=不在任何书名内） */
  book: string | null;
}

export type { PageModel };
