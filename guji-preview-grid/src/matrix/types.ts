// 矩阵布局模型：把解析器的流式 PageModel[] 推导为 1em 基准的字格坐标矩阵
// 坐标系：band（大行）局部坐标，r/c 从 0 起；大字/带圈占 2×2，小字每字 1×1
import type { BlockModel } from "../components/flex/model";

export interface MatrixLargeItem {
  kind: "large";
  r: number;
  c: number;
  ch: string;
}

export interface MatrixCircleItem {
  kind: "circle";
  r: number;
  c: number;
  text: string;
}

export interface MatrixRunItem {
  kind: "run";
  r: number;
  c: number;
  cells: string[];
}

/** 书名框开口边：跨小行 wrap 的连接处去掉边线（替代 flex 版按边删 border 的三态拼接） */
export type BookOpen = "none" | "bottom" | "top" | "both";

export interface MatrixBookItem {
  kind: "book";
  r: number;
  c: number;
  cells: string[];
  open: BookOpen;
}

export type MatrixItem =
  | MatrixLargeItem
  | MatrixCircleItem
  | MatrixRunItem
  | MatrixBookItem;

/** band = 一個大行（.gj 的一个空行分隔块） */
export interface MatrixBand {
  cols: number;
  rows: number;
  items: MatrixItem[];
}

export interface MatrixPage {
  p: number;
  rows: number;
  bands: MatrixBand[];
}

/** 引擎内部：段流（复刻 flex 版 Line.tsx 的 parseLineBlocks 分组顺序） */
export type Seg =
  | { type: "large" | "circle"; text: string }
  | { type: "small"; lines: BlockModel[][] };
