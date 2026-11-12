// Guji IR（中间表示）v1：.gj 等输入 → 语义结构 JSON → 竖排刻本渲染。
// 设计见 docs/design/guji-ir.md。要点：
// - 语义元素不带版面概念（书名 wrap 用 parts 显式表达物理分布，非 start/middle/end 三态）
// - 保真：text 段保留标点/空格；br 保留原文折行；剔除规则属于渲染/评测 profile
// - 稳定 id + 可选 src 源区间：编辑器联动、OCR 对齐、坐标标注的挂靠点

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
}

export interface IRDocument {
  version: 1;
  meta: IRMeta;
  pages: IRPage[];
}

export interface IRPage {
  id: string; // p0312
  no: number;
  src?: [number, number];
  bands: IRBand[];
}

export interface IRBand {
  id: string; // p0312-b3
  ord: number;
  /** 标题大行（#/##/###）：1/2/3 级（书名/集名/部首）；正文大行无此字段 */
  heading?: { level: 1 | 2 | 3; text: string };
  src?: [number, number];
  segments: IRSegment[];
}

export interface IRBookPart {
  /** 书名文本（可含 \n = 带内折行；保留标点） */
  text: string;
  /** 该段所属大行 id；缺省 = 本段所在的大行（跨行 wrap 的后续 part 指向目标行） */
  band?: string;
}

export type IRSegment =
  | { kind: "head"; id: string; char: string; src?: [number, number] } // 行内大字（字头）
  | { kind: "text"; id: string; text: string; src?: [number, number] } // 小字注文段（保真）
  | { kind: "book"; id: string; parts: IRBookPart[]; src?: [number, number] } // 书名框（语义单一元素）
  | { kind: "mark"; id: string; text: string; style: "circled"; src?: [number, number] } // 带圈标
  | { kind: "br" }; // 原文折行（转写保真；无 id）

export type Segment = IRSegment;

// ---- 渲染联动（自 locate.ts 迁移；bandKey/highlight 结构不变） ----

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
