// Guji IR v3：双层结构（允许破坏性更新，替换 v2 内部模型）。
// 设计见 docs/design/guji-ir.md §7。核心原则：
//   骨架决定文本、占格与换行；overlay 描述附着其上的样式或语义。
//   去掉全部 overlay 后，页面仍具有相同的阅读顺序、字格占用与行边界。
//
// 骨架（排版版式）：页 → 大行 → 小行 → 元素
//   - 大字元素：恰好占一个大字格（宽度两小列，高度由书籍版式决定）；合字 ligature:true 时 n 个文本字符合占
//     一个大字格（如 #(十一)）——合字是骨架事实，与圆圈样式无关
//   - 小字元素：每字符占一个小字格（1×1）
//   - 小行 = 排版后的一条小列；auto 模式从字流生成，fold 为历史显式折行
//   - 大字与空位显式入骨架；标题/字头身份由书籍专用语义层解释
// overlay（文档级，单向引用骨架）：
//   - circle：圆圈样式，target 指向元素 id（修饰该元素的字格）
//   - book-title：书名样式/语义，spans 按（行 id，行内码点半开区间）引用；
//     跨行/跨页书名为单一 overlay；骨架中不存在书名锚元素
//
// 单位约定：行内 range 一律 Unicode 码点半开区间（不切开代理对；组合字形／IVS 尚需字形层处理）；
// 源码 src 偏移一律 UTF-16 码元（仅溯源与编辑器联动，渲染不得依赖）。
import type { PageModel } from "../components/flex/model";
import type { IRLayoutConfig, LayoutPresetRef } from "./layout-config";

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
  /** Preserves canonical skeleton text, not a reversible copy of all .gj spelling. */
  fidelity: "full";
  profile: IRProfile;
  /** 解析纯文本时可省略；布局前必须明确选用版式或导入旧数据。 */
  layout?: IRLayoutConfig;
  /** 溯源标识；渲染以 layout 数值快照为准。 */
  layoutPreset?: LayoutPresetRef;
  /** 小行切分来源：auto = 流式＋均式；fold = 历史转写折行 */
  lineLayout: "fold" | "auto";
  orientation: "vertical-rtl";
  /** 行内 range 的单位（码点，半开区间） */
  rangeUnit: "codepoint";
  /** src 偏移的单位（UTF-16 码元；仅溯源/联动，布局渲染不得依赖） */
  srcUnit: "utf-16";
}

export type SizeClass = "large" | "small";

/** 骨架元素：占格事实。大字恰好一个大字格（尺寸由版式定义）（合字 n 字合占一格）；小字每字 1×1 */
export interface IRElement {
  id: string;
  class: SizeClass;
  text: string;
  /** 合字：全部文本字符合占一个大字格（仅 large）；与圆圈样式无关 */
  ligature?: boolean;
}

/** 小行（转写折行；不是带图像坐标的检测行） */
export interface IRLine {
  /** Empty trailing small column in an automatic 1/0 group; preserves alignment. */
  emptyRun?: true;
  id: string; // p0312-b3-l0
  ord: number;
  src?: [number, number]; // UTF-16，原文该行区间
  /** 行规范文本各码点 → 原文 UTF-16 偏移（仅溯源/编辑器联动，渲染不得依赖）。
   *  语法字符（#、【】等）不产出码点故无条目——联动回退语义见 linkage */
  cpSrcs?: number[];
  elements: IRElement[];
}

export interface IRBand {
  /** Explicit $ / ¥ boundary; automatic column boundaries can be reflowed. */
  breakAfter?: boolean;
  id: string; // p0312-b3
  ord: number;
  src?: [number, number];
  lines: IRLine[];
}

export interface IRPage {
  /** 特殊页面的完整几何快照；缺省继承 meta.layout。 */
  layout?: IRLayoutConfig;
  layoutPreset?: LayoutPresetRef;
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
  /** Global reading order, including fragments on other pages. IDs are opaque. */
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

/** 单字定位：large=大字/合字格（元素 id——合字 n 字共享一格）；cell=小字格
 *  （行 + 行规范文本码点，渲染层经 run.rawRanges 起点对位，清洗字符回退前一渲染字） */
export type CharHighlight =
  | { kind: "large"; elId: string }
  | { kind: "cell"; lineId: string; cp: number };

export interface RenderHighlight {
  band: { page: number; index: number } | null;
  /** 光标所在书名 overlay id（null=不在任何书名内） */
  book: string | null;
  /** 光标前一字符的字格（null=文件头或无产出字符处） */
  char: CharHighlight | null;
}

export type { PageModel };
