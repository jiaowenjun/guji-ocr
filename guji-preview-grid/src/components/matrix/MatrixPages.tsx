// 矩阵渲染 v3：L3Page（骨架布局）+ overlay 装饰。
// 主路径：骨架决定占格与换行（layout3）；圆圈/书名框在渲染期按 overlay 绘制——
// 圆环修饰大字格（元素 id 定位）；书名框为覆盖其小字格的跨行矩形（按行+码点
// 区间定位，跨大行 wrap 的连接边开口，与旧 book-start/middle/end 状态无关）。
// 不依赖任何 src 偏移（无 .gj 源的 IR 同样可渲染）。
import { useMemo, type CSSProperties } from "react";
import type { IROverlay, RenderHighlight } from "@/ir/types";
import type { L3Item, L3Page } from "@/ir/layout3";
import { indexLayout, projectBooks, locateCell, type BookBox, type LocatedRun } from "@/ir/projection";
import { getPageFrame } from "./page-frame";

export function MatrixPages({
  pages,
  overlays = [],
  rules = true,
  cells = false,
  highlight,
  onBandClick,
}: {
  pages: L3Page[];
  overlays?: IROverlay[];
  rules?: boolean;
  /** 整页字格（含空白区域，纯视觉叠加，不占布局空间） */
  cells?: boolean;
  highlight?: RenderHighlight;
  onBandClick?: (page: number, index: number) => void;
}) {
  const circled = new Set(
    overlays
      .filter((o): o is Extract<IROverlay, { kind: "circle" }> => o.kind === "circle")
      .map((o) => o.target),
  );
  const index = useMemo(() => indexLayout(pages), [pages]);
  const boxes = useMemo(() => projectBooks(pages, overlays, index), [pages, overlays, index]);

  return (
    <div className="pages">
      {pages.map((pg, i) => (
        <MatrixPageView
          key={i}
          page={pg}
          rules={rules}
          cells={cells}
          circled={circled}
          boxes={boxes.get(pg) ?? []}
          index={index}
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
  cells,
  circled,
  boxes,
  index,
  highlight,
  onBandClick,
}: {
  page: L3Page;
  rules: boolean;
  cells: boolean;
  circled: Set<string>;
  boxes: BookBox[];
  index: Map<string, LocatedRun[]>;
  highlight?: RenderHighlight;
  onBandClick?: (page: number, index: number) => void;
}) {
  const { rowCap, largeRows, largeCols } = page.config;
  const { cols, rows, colOffset } = getPageFrame(page);
  const ch = highlight?.char;
  const activeLargeEl = ch?.kind === "large" ? ch.elId : null;
  const activeCell = ch?.kind === "cell" ? locateCell(index, ch.lineId, ch.cp) : null;
  const pageWarnings = page.diagnostics.filter((d) => d.severity !== "info");

  return (
    <div className="page">
      <div className="page-title" title={pageWarnings.map((d) => d.message).join("；") || undefined}>
        {page.no}{pageWarnings.length > 0 && <span className="m-layout-warning" aria-label="版式需核对"> ⚠</span>}
      </div>
      <div
        className="lines m-lines"
        data-rules={rules ? "on" : "off"}
        data-cells={cells ? "on" : "off"}
        style={
          {
            "--guji-large-rows": largeRows,
            "--guji-large-cols": largeCols,
            gridTemplateColumns: `repeat(${cols}, calc(var(--guji-unit) * 1))`,
            // 行轨用纵向微调后的字格高（版框内容高 ÷ 行数；未注入时回落正方形）
            gridTemplateRows: `repeat(${rows}, calc(var(--guji-unit-v, var(--guji-unit)) * 1))`,
          } as CSSProperties
        }
      >
        <CellRules cols={cols} rows={rows} largeCols={largeCols} largeRows={largeRows} />
        {page.bands.map((band, bi) => {
          const over = band.rows > rowCap;
          // 溢出定位到小列：内容底边（r+全长）越过封顶线的列挂标记——
          // 含整段藏在裁剪区内的项（不渲染但列确实溢出）；大字跨度按版式配置
          const overCols = new Set<number>();
          if (over) {
            for (const it of band.items) {
              const span = it.kind === "large" ? largeRows : (it.cells?.length ?? 0);
              if (it.r + span <= rows) continue;
              overCols.add(it.c);
              if (it.kind === "large") for (let col = 1; col < largeCols; col++) overCols.add(it.c + col);
            }
          }
          return (
            <div
              key={bi}
              className={`m-band${
                highlight?.band?.page === page.no && highlight.band.index === bi ? " m-band-active" : ""
              }${page.colStarts[bi] + colOffset === 0 ? " m-band-last" : ""}${over ? " m-band-over" : ""}`}
              title={page.diagnostics.filter((d) => d.bandId === band.id).map((d) => d.message).join("；") || undefined}
              onClick={onBandClick ? () => onBandClick(page.no, bi) : undefined}
              style={
                {
                  gridColumn: `${page.colStarts[bi] + colOffset + 1} / span ${band.cols}`,
                  gridRow: "1 / -1",
                } as CSSProperties
              }
            >
              {band.items.map((item, ii) => {
                const cellIdx =
                  activeCell && item === activeCell.item
                    ? activeCell.index
                    : undefined;
                return (
                  <ItemView
                    key={ii}
                    item={item}
                    circled={circled}
                    activeLarge={item.kind === "large" && item.elId === activeLargeEl}
                    activeCell={cellIdx}
                    rowCap={rows}
                    largeRows={largeRows}
                    largeCols={largeCols}
                  />
                );
              })}
              {[...overCols].map((c) => (
                // 溢出小列警示：占该列最后一格轨道，贴底 2px 即裁剪边
                <div
                  key={`ov${c}`}
                  className="m-over-mark"
                  style={{ gridRow: rows, gridColumn: c + 1 } as CSSProperties}
                />
              ))}
            </div>
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
                gridColumn: `${box.col + colOffset + 1} / span ${box.cols ?? 1}`,
                ...(box.halfShift
                  ? { transform: `translateX(calc(var(--guji-unit) * ${box.halfShift}))` }
                  : {}),
              } as CSSProperties
            }
          />
          );
        })}
      </div>
    </div>
  );
}

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
}) {
  // 注意：ItemView 是 .m-band（subgrid 项）的子元素，列号用 band 局部坐标；
  // 页级换算（colStarts）只用于书名框等 .m-lines 直接子元素
  if (item.kind === "large") {
    const span = Math.min(largeRows, rowCap - item.r);
    if (span <= 0) return null;
    const clipped = span < largeRows;
    const text = item.text ?? "";
    const stacked = item.ligature && [...text].length > 1;
    const gridPos = {
      gridRow: `${item.r + 1} / span ${span}`,
      gridColumn: `${item.c + 1} / span ${largeCols}`,
    } as CSSProperties;
    const active = activeLarge ? " m-char-active" : "";
    const cut = clipped ? " m-clipped" : "";
    if (circled.has(item.elId ?? "")) {
      return (
        <div className={`m-circle${active}${cut}`} style={gridPos}>
          <div className="m-ring">{stacked ? <span className="stack">{text}</span> : text}</div>
        </div>
      );
    }
    return (
      <div className={`m-large${active}${cut}`} style={gridPos}>
        {stacked ? <span className="stack">{text}</span> : text}
      </div>
    );
  }
  const full = item.cells?.length ?? 0;
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
      {item.cells?.map((ch, i) => (
        <div key={i} className={i === activeCell ? "m-cell m-char-active" : "m-cell"}>
          {ch}
        </div>
      ))}
    </div>
  );
}
