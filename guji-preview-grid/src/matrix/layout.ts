// 矩阵布局引擎：PageModel[] → MatrixPage[]
// 几何语义复刻 flex 渲染（vscode-guji-preview）：
// - 复合行按 parseLineBlocks 相同的分组产生段流：[前置小字组] (大字+可选小字组)* [尾随小字组]
// - 小字组：每个小行一列（1em），小行 0在最右（row-reverse 语义），组内居中取整
//   （flex 为 auto-margin 精确居中，W−k 为奇数时有 0.5em 亚格偏差，此处取整，语料 k 恒为 2 不触发）
// - band 宽 W = max(2, 最宽小字组列数)；大字恒在 band 局部列 0-1
// - 书名合并：同一小行内连续的 book 类片段合并为一个矩形 book 项（单一边框），
//   跨小行 wrap 的连接边按 open 去线；彻底替代 flex 版 book-start/middle/end + 负边距拼接
import type { BlockModel, LineModel, PageModel } from "../components/flex/model";
import type {
  MatrixBand,
  MatrixItem,
  MatrixPage,
  Seg,
} from "./types";

/** 段流划分：与 flex 版 parseLineBlocks 完全一致的分组算法 */
function segments(blocks: BlockModel[]): Seg[] {
  const segs: Seg[] = [];
  let smallLines: BlockModel[][] = [];
  let frags: BlockModel[] = [];

  const mergeFrags = () => {
    if (frags.length > 0) {
      smallLines.push(frags);
      frags = [];
    }
  };
  const mergeSmallLines = () => {
    if (smallLines.length > 0) {
      segs.push({ type: "small", lines: smallLines });
      smallLines = [];
    }
  };

  blocks.forEach((blk) => {
    if (blk.si === "large" && blk.t) {
      mergeFrags();
      mergeSmallLines();
      segs.push({
        type: blk.st === "circle" ? "circle" : "large",
        text: blk.t,
      });
    } else if (blk.st === "br") {
      mergeFrags();
    } else {
      frags.push(blk);
    }
  });

  mergeFrags();
  mergeSmallLines();
  return segs;
}

/** 一个小行内的片段 → 纵向堆叠的 items；返回行数 */
function placeLine(
  frags: BlockModel[],
  r0: number,
  col: number,
  items: MatrixItem[]
): number {
  let r = r0;
  // 当前未闭合的普通字串
  let run: { start: number; cells: string[] } | null = null;
  // 当前未闭合的书名串（连续 book 类片段合并）
  let book: { start: number; cells: string[]; openTop: boolean } | null = null;
  let bookEndsOpen = false; // 书名串最后一个片段是否开口向下（start/middle）

  const flushRun = () => {
    if (run && run.cells.length > 0) {
      items.push({ kind: "run", r: run.start, c: col, cells: run.cells });
    }
    run = null;
  };
  const flushBook = () => {
    if (book && book.cells.length > 0) {
      const openTop = book.openTop;
      const openBottom = bookEndsOpen;
      items.push({
        kind: "book",
        r: book.start,
        c: col,
        cells: book.cells,
        open:
          openTop && openBottom
            ? "both"
            : openBottom
              ? "bottom"
              : openTop
                ? "top"
                : "none",
      });
    }
    book = null;
    bookEndsOpen = false;
  };

  frags.forEach((frag) => {
    const cells = frag.t ? [...frag.t] : [];
    if (cells.length === 0) return;
    const isBook =
      frag.st === "book" ||
      frag.st === "book-start" ||
      frag.st === "book-middle" ||
      frag.st === "book-end";

    if (isBook) {
      flushRun();
      if (!book) {
        // 新书名串：首片段为 middle/end 则向上开口（承接上一列的续文）
        book = {
          start: r,
          cells: [],
          openTop: frag.st === "book-middle" || frag.st === "book-end",
        };
        bookEndsOpen = false;
      }
      book.cells.push(...cells);
      // 尾片段为 start/middle 则向下开口（读序流出到左侧下一列）
      bookEndsOpen = frag.st === "book-start" || frag.st === "book-middle";
    } else {
      flushBook();
      if (!run) {
        run = { start: r, cells: [] };
      }
      run.cells.push(...cells);
    }
    r += cells.length;
  });

  flushRun();
  flushBook();
  return r - r0;
}

/** 复合行 → band */
function layoutComposite(blocks: BlockModel[]): MatrixBand {
  const segs = segments(blocks);
  const ks = segs
    .filter((s): s is Extract<Seg, { type: "small" }> => s.type === "small")
    .map((s) => s.lines.length);
  const cols = Math.max(2, ...ks);
  const items: MatrixItem[] = [];
  let r = 0;

  for (const seg of segs) {
    if (seg.type === "small") {
      const k = seg.lines.length;
      const start = Math.floor((cols - k) / 2);
      let groupRows = 0;
      seg.lines.forEach((frags, j) => {
        // 小行 0 在最右（复刻 row-reverse）
        const col = start + (k - 1 - j);
        const rows = placeLine(frags, r, col, items);
        groupRows = Math.max(groupRows, rows);
      });
      r += groupRows;
    } else {
      items.push(
        seg.type === "circle"
          ? { kind: "circle", r, c: 0, text: seg.text }
          : { kind: "large", r, c: 0, ch: seg.text }
      );
      r += 2;
    }
  }

  return { cols, rows: r, items };
}

/** 单个行模型 → band */
function layoutBand(model: LineModel): MatrixBand {
  if ("c" in model) {
    return layoutComposite(model.c);
  }
  if (model.si === "large" && model.t) {
    // 标题行：逐字 2×2，缩进 i 即顶部留 i 个大字位（空格不物化为项）
    const indent = model.i ?? 0;
    const items = [...model.t].map((ch, idx) => ({
      kind: "large" as const,
      r: 2 * (indent + idx),
      c: 0,
      ch,
    }));
    return { cols: 2, rows: 2 * (indent + [...model.t].length), items };
  }
  // 空大字列（st: "empty"）：纯空白 band
  return { cols: 2, rows: 2, items: [] };
}

export function layoutPages(pageModels: PageModel[]): MatrixPage[] {
  return pageModels.map((pm) => {
    const bands = pm.l.map(layoutBand);
    const rows = Math.max(2, ...bands.map((b) => b.rows));
    return { p: pm.p, rows, bands };
  });
}
