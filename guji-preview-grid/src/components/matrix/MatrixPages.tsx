// 矩阵渲染 v3：L3Page（骨架布局）+ overlay 装饰。
// 主路径：骨架决定占格与换行（layout3）；圆圈/书名框在渲染期按 overlay 绘制——
// 圆环修饰大字格（元素 id 定位）；书名框为覆盖其小字格的跨行矩形（按行+码点
// 区间定位，跨大行 wrap 的连接边开口，与旧 book-start/middle/end 状态无关）。
// 不依赖任何 src 偏移（无 .gj 源的 IR 同样可渲染）。
import { memo, useMemo, type CSSProperties, type DOMAttributes } from "react";
import type { CharHighlight, IROverlay, RenderHighlight } from "@/ir/types";
import type { L3Band, L3Item, L3Page } from "@/ir/layout3";
import { indexLayout, projectBooks, locateCell, type BookBox } from "@/ir/projection";
import { getPageFrame } from "@/ir/page-frame";
import type { IRLayoutConfig } from "@/ir/layout-config";
import { getItemBounds } from "@/ir/layout-geometry";
import { PagePaper, type PagePaperLayout } from "./PagePaper";

export function MatrixPages({
  pages,
  overlays = [],
  rules = true,
  cells = false,
  highlight,
  onBandClick,
  onCharDoubleClick,
  paper,
}: {
  pages: L3Page[];
  overlays?: IROverlay[];
  rules?: boolean;
  /** 整页字格（含空白区域，纯视觉叠加，不占布局空间） */
  cells?: boolean;
  highlight?: RenderHighlight;
  onBandClick?: (page: number, index: number) => void;
  onCharDoubleClick?: (char: CharHighlight) => void;
  paper?: PagePaperLayout;
}) {
  const circled = new Set(
    overlays
      .filter((o): o is Extract<IROverlay, { kind: "circle" }> => o.kind === "circle")
      .map((o) => o.target),
  );
  const index = useMemo(() => indexLayout(pages), [pages]);
  const boxes = useMemo(() => projectBooks(pages, overlays, index), [pages, overlays, index]);
  const ch = highlight?.char;
  // 全部页面共用布局索引，只定位一次；每列再筛选属于自己的命中项。
  const activeCell = ch?.kind === "cell" ? locateCell(index, ch.lineId, ch.cp) : null;

  return (
    <div className="pages" style={paper ? { gap: paper.unit * 1.5 } : undefined}>
      {pages.map((pg, i) => (
        <PagePaper key={i} pageNo={pg.no} diagnostics={pg.diagnostics} layout={paper}>
          <MatrixPageView
            page={pg}
            rules={rules}
            cells={cells}
            circled={circled}
            boxes={boxes.get(pg) ?? []}
            activeCell={activeCell}
            highlight={highlight}
            onBandClick={onBandClick}
            onCharDoubleClick={onCharDoubleClick}
          />
        </PagePaper>
      ))}
    </div>
  );
}

function MatrixPageView({
  page,
  rules,
  cells,
  circled,
  boxes,
  activeCell,
  highlight,
  onBandClick,
  onCharDoubleClick,
}: {
  page: L3Page;
  rules: boolean;
  cells: boolean;
  circled: Set<string>;
  boxes: BookBox[];
  activeCell: ReturnType<typeof locateCell>;
  highlight?: RenderHighlight;
  onBandClick?: (page: number, index: number) => void;
  onCharDoubleClick?: (char: CharHighlight) => void;
}) {
  const { largeRows, largeCols } = page.config;
  const { cols, rows, colOffset } = getPageFrame(page);
  // 正文保留完整轨道并靠右，超出版框的轨道从左侧裁掉。
  // 不把负偏移写入 gridColumn：CSS 的负行号是从末端倒数，会造成重排。
  const contentCols = Math.max(cols, page.totalCols);
  const contentOffset = Math.max(0, colOffset);
  const hiddenCols = Math.max(0, -colOffset);
  const leftOverflowLabel = `向左溢出：超出版框的 ${hiddenCols} 个小列已隐藏，请校对分列`;
  const ch = highlight?.char;
  const activeLargeEl = ch?.kind === "large" ? ch.elId : null;

  return (
    <div
      className="lines m-lines"
      data-rules={rules ? "on" : "off"}
      data-cells={cells ? "on" : "off"}
      style={
        {
          "--guji-large-rows": largeRows,
          "--guji-large-cols": largeCols,
          "--guji-default-unit-v": `calc(var(--guji-unit) * ${largeCols} / ${largeRows})`,
          gridTemplateColumns: `repeat(${cols}, calc(var(--guji-unit) * 1))`,
          // 行轨用纵向微调后的字格高（版框内容高 ÷ 行数；未注入时按大字格等宽高推导）
          gridTemplateRows: `repeat(${rows}, calc(var(--guji-unit-v, var(--guji-default-unit-v)) * 1))`,
        } as CSSProperties
      }
    >
      <CellRules cols={cols} rows={rows} largeCols={largeCols} largeRows={largeRows} />
      <div
        className="m-content"
        style={{ gridTemplateColumns: `repeat(${contentCols}, calc(var(--guji-unit) * 1))` }}
      >
        {page.bands.map((band, bi) => {
          const activeItem = band.items.find((item) =>
            item.kind === "large" ? item.elId === activeLargeEl : item === activeCell?.item,
          ) ?? null;
          return (
            <MatrixBand
              key={bi}
              band={band}
              config={page.config}
              pageNo={page.no}
              bandIndex={bi}
              colStart={page.colStarts[bi] + contentOffset}
              atLeftEdge={page.colStarts[bi] + colOffset === 0}
              warning={page.diagnostics.filter((d) => d.bandId === band.id).map((d) => d.message).join("；")}
              circled={circled}
              active={highlight?.band?.page === page.no && highlight.band.index === bi}
              activeItem={activeItem}
              activeCell={activeItem?.kind === "run" ? activeCell?.index : undefined}
              onBandClick={onBandClick}
              onCharDoubleClick={onCharDoubleClick}
            />
          );
        })}
        {boxes.map((box, i) => {
          // 封顶同款钳制：框底不越版面下线；整框在裁剪区则不渲染
          const span = Math.min(box.rowEnd, rows) - box.rowStart;
          if (span <= 0) return null;
          return (
            <div
              key={`bk${i}`}
              className={[
                "m-book",
                box.openTop && "open-top",
                box.openBottom && "open-bottom",
                // 最右列（读序第一列）：右边线叠上版框（matrix.css 共线避让）
                box.col + (box.cols ?? 1) === page.totalCols && "m-flush-r",
                // band 左缘列（版框最左边除外）：界栏开时与界栏共线
                box.col === page.colStarts[box.bandIdx] &&
                  box.col + colOffset > 0 &&
                  "at-band-left",
                highlight?.book === box.overlayId && "m-book-active",
              ]
                .filter(Boolean)
                .join(" ")}
              style={
                {
                  gridRow: `${box.rowStart + 1} / span ${span}`,
                  gridColumn: `${box.col + contentOffset + 1} / span ${box.cols ?? 1}`,
                  ...(box.halfShift
                    ? { transform: `translateX(calc(var(--guji-unit) * ${box.halfShift}))` }
                    : {}),
                } as CSSProperties
              }
            />
          );
        })}
      </div>
      {hiddenCols > 0 && (
        <div className="m-over-left" role="img" aria-label={leftOverflowLabel} title={leftOverflowLabel}>
          <span aria-hidden="true">←</span>
        </div>
      )}
    </div>
  );
}

/** 每列仅接收自己的高亮；memo 跳过 map 中高亮未变的列。 */
const MatrixBand = memo(function MatrixBand({
  band, config, pageNo, bandIndex, colStart, atLeftEdge, warning,
  circled, active, activeItem, activeCell, onBandClick, onCharDoubleClick,
}: {
  band: L3Band;
  config: IRLayoutConfig;
  pageNo: number;
  bandIndex: number;
  colStart: number;
  atLeftEdge: boolean;
  warning: string;
  circled: Set<string>;
  active: boolean;
  activeItem: L3Item | null;
  activeCell?: number;
  onBandClick?: (page: number, index: number) => void;
  onCharDoubleClick?: (char: CharHighlight) => void;
}) {
  const overCols = new Set<number>();
  if (band.rows > config.rowCap) {
    // 包含完全位于裁剪区的项；红条定位到实际溢出的小列。
    for (const item of band.items) {
      const { x, y, width, height } = getItemBounds(item, config);
      if (y + height <= config.rowCap) continue;
      for (let col = 0; col < width; col++) overCols.add(x + col);
    }
  }
  const overflowLabel = `第 ${bandIndex + 1} 大列向下溢出，超出 ${config.rowCap} 小格的文字已隐藏`;
  return (
    <div
      className={`m-band${active ? " m-band-active" : ""}${atLeftEdge ? " m-band-last" : ""}`}
      title={warning || undefined}
      onClick={onBandClick ? () => onBandClick(pageNo, bandIndex) : undefined}
      style={{ gridColumn: `${colStart + 1} / span ${band.cols}`, gridRow: "1 / -1" }}
    >
      {band.items.map((item, i) => (
        <ItemView
          key={i}
          item={item}
          circled={circled}
          activeLarge={item.kind === "large" && item === activeItem}
          activeCell={item === activeItem ? activeCell : undefined}
          rowCap={config.rowCap}
          largeRows={config.largeRows}
          largeCols={config.largeCols}
          onCharDoubleClick={onCharDoubleClick}
        />
      ))}
      {[...overCols].map((c) => (
        <div
          key={`ov${c}`}
          className="m-over-mark"
          role="img"
          aria-label={overflowLabel}
          title={overflowLabel}
          style={{
            gridRow: config.rowCap,
            gridColumn: Math.floor(c) + 1,
            ...(c % 1 ? { transform: `translateX(calc(var(--guji-unit) * ${c % 1}))` } : {}),
          }}
        />
      ))}
    </div>
  );
});

/** 每条线直接定位到正文的 Grid 轨道；绝对定位不参与轨道尺寸计算。
 *  不用 background 平铺：Safari 对小数 tile 取整会造成整页累计偏移。
 *  只画内部分隔，四周复用版框的 1px 实线，避免边缘叠成双线。 */
function CellRules({ cols, rows, largeCols, largeRows }: {
  cols: number;
  rows: number;
  largeCols: number;
  largeRows: number;
}) {
  return (
    <>
      {Array.from({ length: cols - 1 }, (_, i) => (
        <span
          key={`v${i}`}
          aria-hidden="true"
          className={`m-cell-rule m-cell-rule-v${(i + 1) % largeCols ? " m-cell-rule-minor" : ""}`}
          style={{ gridColumn: `${i + 2} / ${i + 3}`, gridRow: "1 / -1" }}
        />
      ))}
      {Array.from({ length: rows - 1 }, (_, i) => (
        <span
          key={`h${i}`}
          aria-hidden="true"
          className={`m-cell-rule m-cell-rule-h${(i + 1) % largeRows ? " m-cell-rule-minor" : ""}`}
          style={{ gridRow: `${i + 2} / ${i + 3}`, gridColumn: "1 / -1" }}
        />
      ))}
    </>
  );
}

function ItemView({
  item,
  circled,
  activeLarge,
  activeCell,
  rowCap,
  largeRows,
  largeCols,
  onCharDoubleClick,
}: {
  item: L3Item;
  circled: Set<string>;
  /** 单字联动：光标前一字符为该大字/合字格 */
  activeLarge?: boolean;
  /** 单字联动：光标前一字符为该 run 的第 activeCell 字 */
  activeCell?: number;
  /** 页面可见行数（封顶后）；条目跨度超出部分被裁剪 */
  rowCap: number;
  largeRows: number;
  largeCols: number;
  onCharDoubleClick?: (char: CharHighlight) => void;
}) {
  const charEvents = (char: CharHighlight): DOMAttributes<HTMLDivElement> => onCharDoubleClick ? {
    // 双击前的两次 click 不冒泡到列首定位；列内背景仍保留单击定位。
    onClick: (event) => event.stopPropagation(),
    onMouseDown: (event) => {
      // 浏览器在第二次按下时选择词语；保留首次按下及拖动的普通文本选择。
      if (event.detail > 1) event.preventDefault();
    },
    onDoubleClick: (event) => {
      event.preventDefault();
      event.stopPropagation();
      onCharDoubleClick(char);
    },
  } : {};
  // 注意：ItemView 是 .m-band（subgrid 项）的子元素，列号用 band 局部坐标；
  // 页级换算（colStarts）只用于书名框等 .m-content 直接子元素
  if (item.kind === "large") {
    const span = Math.min(largeRows, rowCap - item.r);
    if (span <= 0) return null;
    const clipped = span < largeRows;
    const text = item.text;
    const stacked = item.ligature && [...text].length > 1;
    const gridPos = {
      gridRow: `${item.r + 1} / span ${span}`,
      gridColumn: `${item.c + 1} / span ${largeCols}`,
    } as CSSProperties;
    const active = activeLarge ? " m-char-active" : "";
    const cut = clipped ? " m-clipped" : "";
    if (circled.has(item.elId)) {
      return (
        <div className={`m-circle${active}${cut}`} style={gridPos} {...charEvents({ kind: "large", elId: item.elId })}>
          <div className="m-ring">{stacked ? <span className="stack">{text}</span> : text}</div>
        </div>
      );
    }
    return (
      <div className={`m-large${active}${cut}`} style={gridPos} {...charEvents({ kind: "large", elId: item.elId })}>
        {stacked ? <span className="stack">{text}</span> : text}
      </div>
    );
  }
  const full = item.cells.length;
  const span = Math.min(full, rowCap - item.r);
  if (span <= 0) return null;
  return (
    <div
      className={`m-run${span < full ? " m-clipped" : ""}`}
      style={
        {
          gridRow: `${item.r + 1} / span ${span}`,
          gridColumn: `${item.c + 1}`,
          // 奇数余量小字组的亚格居中（transform 平移——margin 会挤压固定轨道内的内容宽）
          ...(item.halfShift
            ? { transform: `translateX(calc(var(--guji-unit) * ${item.halfShift}))` }
            : {}),
        } as CSSProperties
      }
    >
      {item.cells.map((ch, i) => (
        <div
          key={i}
          className={i === activeCell ? "m-cell m-char-active" : "m-cell"}
          {...charEvents({ kind: "cell", lineId: item.lineId, cp: item.rawRanges[i][0] })}
        >
          {ch}
        </div>
      ))}
    </div>
  );
}
