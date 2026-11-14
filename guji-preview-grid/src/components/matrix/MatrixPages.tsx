// 矩阵渲染 v3：L3Page（骨架布局）+ overlay 装饰。
// 主路径：骨架决定占格与换行（layout3）；圆圈/书名框在渲染期按 overlay 绘制——
// 圆环修饰大字格（元素 id 定位）；书名框为覆盖其小字格的跨行矩形（按行+码点
// 区间定位，跨大行 wrap 的连接边开口，与旧 book-start/middle/end 状态无关）。
// 不依赖任何 src 偏移（无 .gj 源的 IR 同样可渲染）。
import type { CSSProperties } from "react";
import type { IRBookOverlay, IROverlay, RenderHighlight } from "@/ir/types";
import type { L3Item, L3Page } from "@/ir/layout3";

interface BookBox {
  overlayId: string;
  bandIdx: number;
  rowStart: number; // 页级行（cell）
  rowEnd: number; // 半开
  col: number; // 页级列
  openTop: boolean;
  openBottom: boolean;
  /** 所属 run 的亚格居中偏移（奇数余量组） */
  halfShift?: 0.5;
}

/** 行 id → band 序（行 id 形如 pXXXX-bN-lM，band id 即其去掉 -lM 前缀） */
function bandIndexOfLine(page: L3Page, lineId: string): number | undefined {
  const bandId = lineId.replace(/-l\d+$/, "");
  const idx = page.bands.findIndex((b) => b.id === bandId);
  return idx >= 0 ? idx : undefined;
}

/** 书名 overlay → 覆盖矩形（经 run 项的 lineId/rawOffsets 定位；纯骨架坐标）。
 *  每条 span 一个框（span 不跨行）；跨小行/跨大行 wrap 的开口方向按阅读序
 *  （band 序、行序——列自右而左）判定：本框之前还有 span 则 open-top，之后还有则 open-bottom */
function bookBoxesFor(page: L3Page, overlay: IRBookOverlay): BookBox[] {
  // 各 span 的阅读序位置（bandIdx, lineOrd）
  const spanPos = overlay.spans.map((span) => {
    const bandIdx = bandIndexOfLine(page, span.line);
    const lineOrd = bandIdx !== undefined ? Number(span.line.replace(/.*-l/, "")) : -1;
    return { key: bandIdx !== undefined ? bandIdx * 1000 + lineOrd : -1 };
  });

  return overlay.spans.flatMap((span, si) => {
    const bandIdx = bandIndexOfLine(page, span.line);
    if (bandIdx === undefined) return [];
    const band = page.bands[bandIdx];
    let rowMin = Infinity;
    let rowMax = -Infinity;
    let col = -1;
    let halfShift: 0.5 | undefined;
    for (const item of band.items) {
      if (item.kind !== "run" || item.lineId !== span.line) continue;
      // span 是行规范文本（未清洗）坐标；cells 是清洗后逐字——经 rawOffsets 对位：
      // 覆盖 = 原文偏移落在 [range0, range1) 内的清洗字
      const offs = item.rawOffsets ?? [];
      let first = -1;
      let last = -1;
      offs.forEach((o, k) => {
        if (o >= span.range[0] && o < span.range[1]) {
          if (first < 0) first = k;
          last = k;
        }
      });
      if (first < 0) continue;
      rowMin = Math.min(rowMin, item.r + first);
      rowMax = Math.max(rowMax, item.r + last);
      col = page.colStarts[bandIdx] + item.c;
      halfShift = item.halfShift;
    }
    if (rowMin === Infinity || col < 0) return [];
    const key = spanPos[si].key;
    const hasEarlier = spanPos.some((p, j) => j !== si && p.key !== -1 && p.key < key);
    const hasLater = spanPos.some((p, j) => j !== si && p.key !== -1 && p.key > key);
    return [
      {
        overlayId: overlay.id,
        bandIdx,
        rowStart: rowMin,
        rowEnd: rowMax + 1,
        col,
        halfShift,
        // 开口 = 前/后有延续 span，或语义边界：孤立】延续（!openedHere）开口向上；
        // 未见】的流出（!closed，如 EOF 未闭合书名）开口向下
        openTop: hasEarlier || overlay.openedHere === false,
        openBottom: hasLater || overlay.closed === false,
      },
    ];
  });
}

export function MatrixPages({
  pages,
  overlays = [],
  rules = true,
  highlight,
  onBandClick,
}: {
  pages: L3Page[];
  overlays?: IROverlay[];
  rules?: boolean;
  highlight?: RenderHighlight;
  onBandClick?: (page: number, index: number) => void;
}) {
  const circled = new Set(
    overlays
      .filter((o): o is Extract<IROverlay, { kind: "circle" }> => o.kind === "circle")
      .map((o) => o.target),
  );
  const books = overlays.filter((o): o is IRBookOverlay => o.kind === "book-title");

  return (
    <div className="pages">
      {pages.map((pg, i) => (
        <MatrixPageView
          key={i}
          page={pg}
          rules={rules}
          circled={circled}
          books={books}
          highlight={highlight}
          onBandClick={onBandClick}
        />
      ))}
    </div>
  );
}

function MatrixPageView({
  page,
  rules,
  circled,
  books,
  highlight,
  onBandClick,
}: {
  page: L3Page;
  rules: boolean;
  circled: Set<string>;
  books: IRBookOverlay[];
  highlight?: RenderHighlight;
  onBandClick?: (page: number, index: number) => void;
}) {
  const boxes = books.flatMap((ov) => bookBoxesFor(page, ov));

  // 单字高亮解析：large 按元素 id 直查；cell 经 run.rawOffsets 对位——
  // 光标前一字若被清洗（标点）无精确条目，回退到 ≤cp 的最大偏移（前一渲染字）
  let activeLargeEl: string | null = null;
  let activeCell: { lineId: string; index: number } | null = null;
  const ch = highlight?.char;
  if (ch?.kind === "large") activeLargeEl = ch.elId;
  else if (ch) {
    const bandIdx = bandIndexOfLine(page, ch.lineId);
    if (bandIdx !== undefined) {
      for (const item of page.bands[bandIdx].items) {
        if (item.kind !== "run" || item.lineId !== ch.lineId) continue;
        const offs = item.rawOffsets ?? [];
        let k = -1;
        for (let x = 0; x < offs.length; x++) if (offs[x] <= ch.cp) k = x;
        if (k >= 0) activeCell = { lineId: ch.lineId, index: k };
        break;
      }
    }
  }

  return (
    <div className="page">
      <div className="page-title">{page.no}</div>
      <div
        className="lines m-lines"
        data-rules={rules ? "on" : "off"}
        style={
          {
            gridTemplateColumns: `repeat(${page.totalCols}, calc(var(--guji-unit) * 1))`,
            // 行轨用纵向微调后的字格高（版框内容高 ÷ 行数；未注入时回落正方形）
            gridTemplateRows: `repeat(${page.rows}, calc(var(--guji-unit-v, var(--guji-unit)) * 1))`,
          } as CSSProperties
        }
      >
        {page.bands.map((band, bi) => (
          <div
            key={bi}
            className={`m-band${
              highlight?.band?.page === page.no && highlight.band.index === bi ? " m-band-active" : ""
            }${bi === page.bands.length - 1 ? " m-band-last" : ""}`}
            onClick={onBandClick ? () => onBandClick(page.no, bi) : undefined}
            style={
              {
                gridColumn: `${page.colStarts[bi] + 1} / span ${band.cols}`,
                gridRow: "1 / -1",
              } as CSSProperties
            }
          >
            {band.items.map((item, ii) => {
              const cellIdx =
                activeCell && item.kind === "run" && item.lineId === activeCell.lineId
                  ? activeCell.index
                  : undefined;
              return (
                <ItemView
                  key={ii}
                  item={item}
                  circled={circled}
                  activeLarge={item.kind === "large" && item.elId === activeLargeEl}
                  activeCell={cellIdx}
                />
              );
            })}
          </div>
        ))}
        {boxes.map((box, i) => (
          <div
            key={`bk${i}`}
            className={[
              "m-book",
              box.openTop && "open-top",
              box.openBottom && "open-bottom",
              // 最右列（读序第一列）：右边线叠上版框（matrix.css 共线避让）
              box.col === page.totalCols - 1 && "m-flush-r",
              // band 左缘列（最右 band 除外——其左缘是版框）：界栏开时与界栏共线
              box.col === page.colStarts[box.bandIdx] &&
                box.bandIdx < page.bands.length - 1 &&
                "at-band-left",
              highlight?.book === box.overlayId && "m-book-active",
            ]
              .filter(Boolean)
              .join(" ")}
            style={
              {
                gridRow: `${box.rowStart + 1} / span ${box.rowEnd - box.rowStart}`,
                gridColumn: `${box.col + 1} / span 1`,
                ...(box.halfShift
                  ? { transform: `translateX(calc(var(--guji-unit) * ${box.halfShift}))` }
                  : {}),
              } as CSSProperties
            }
          />
        ))}
      </div>
    </div>
  );
}

function ItemView({
  item,
  circled,
  activeLarge,
  activeCell,
}: {
  item: L3Item;
  circled: Set<string>;
  /** 单字联动：光标前一字符为该大字/合字格 */
  activeLarge?: boolean;
  /** 单字联动：光标前一字符为该 run 的第 activeCell 字 */
  activeCell?: number;
}) {
  // 注意：ItemView 是 .m-band（subgrid 项）的子元素，列号用 band 局部坐标；
  // 页级换算（colStarts）只用于书名框等 .m-lines 直接子元素
  if (item.kind === "large") {
    const text = item.text ?? "";
    const stacked = item.ligature && [...text].length > 1;
    const gridPos = {
      gridRow: `${item.r + 1} / span 2`,
      gridColumn: `${item.c + 1} / span 2`,
    } as CSSProperties;
    const active = activeLarge ? " m-char-active" : "";
    if (circled.has(item.elId ?? "")) {
      return (
        <div className={`m-circle${active}`} style={gridPos}>
          <div className="m-ring">{stacked ? <span className="stack">{text}</span> : text}</div>
        </div>
      );
    }
    return (
      <div className={`m-large${active}`} style={gridPos}>
        {stacked ? <span className="stack">{text}</span> : text}
      </div>
    );
  }
  return (
    <div
      className="m-run"
      style={
        {
          gridRow: `${item.r + 1} / span ${item.cells?.length ?? 0}`,
          gridColumn: `${item.c + 1}`,
          // 奇数余量小字组的亚格居中（transform 平移——margin 会挤压固定轨道内的内容宽）
          ...(item.halfShift
            ? { transform: `translateX(calc(var(--guji-unit) * ${item.halfShift}))` }
            : {}),
        } as CSSProperties
      }
    >
      {item.cells?.map((ch, i) => (
        <div key={i} className={i === activeCell ? "m-cell m-char-active" : "m-cell"}>
          {ch}
        </div>
      ))}
    </div>
  );
}
