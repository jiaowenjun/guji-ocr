// Grid 矩阵渲染：MatrixPage[] → 严格字格矩阵 DOM
// 页 = 显式轨道 grid（1em 基准）；band（大行）= subgrid 项占满整页高，
// 其 border-left 即贯通界栏（data-rules 开关）；band 0（首个大行）放在最右列
import type { CSSProperties } from "react";
import type { MatrixItem, MatrixPage } from "@/matrix/types";
import { bandKey, type RenderHighlight } from "@/ir/types";

/** 页面横向字格数（含 band 间无缝拼接）；渲染页宽 = pageColumns × unit + 2px 边框。
 *  供组件内部与外部（如数据集对照页的同宽联动）共用，避免两处漂移。 */
export function pageColumns(page: MatrixPage): number {
  let acc = 0;
  for (const band of page.bands) acc += band.cols;
  return Math.max(2, acc);
}

export function MatrixPages({
  pages,
  rules = true,
  highlight,
  onBandClick,
}: {
  pages: MatrixPage[];
  rules?: boolean;
  /** 编辑器光标联动高亮（大行/书名） */
  highlight?: RenderHighlight;
  onBandClick?: (page: number, index: number) => void;
}) {
  return (
    <div className="pages">
      {pages.map((pg, i) => (
        <MatrixPageView key={i} page={pg} rules={rules} highlight={highlight} onBandClick={onBandClick} />
      ))}
    </div>
  );
}

function MatrixPageView({
  page,
  rules,
  highlight,
  onBandClick,
}: {
  page: MatrixPage;
  rules: boolean;
  highlight?: RenderHighlight;
  onBandClick?: (page: number, index: number) => void;
}) {
  // band 0 在最右：colStart = 排在其右侧的所有 band 宽度之和
  const colStarts: number[] = [];
  let acc = 0;
  for (let i = page.bands.length - 1; i >= 0; i--) {
    colStarts[i] = acc;
    acc += page.bands[i].cols;
  }
  const totalCols = pageColumns(page);

  return (
    <div className="page">
      <div className="page-title">{page.p}</div>
      <div
        className="lines m-lines"
        data-rules={rules ? "on" : "off"}
        style={
          {
            gridTemplateColumns: `repeat(${totalCols}, calc(var(--guji-unit) * 1))`,
            gridTemplateRows: `repeat(${page.rows}, calc(var(--guji-unit) * 1))`,
          } as CSSProperties
        }
      >
        {page.bands.map((band, bi) => {
          // 书名高亮：本 band 内各书名 item 的序号落在区间段内则点亮
          const runs = highlight?.book?.[bandKey(page.p, bi)];
          const bookActive = band.items.map(() => false);
          let ord = 0;
          band.items.forEach((item, i) => {
            if (item.kind === "book") {
              if (runs?.some((r) => ord >= r.start && ord < r.start + r.count)) {
                bookActive[i] = true;
              }
              ord++;
            }
          });
          const bandActive =
            highlight?.band?.page === page.p && highlight.band.index === bi;
          return (
            <div
              key={bi}
              className={`m-band${bandActive ? " m-band-active" : ""}`}
              onClick={onBandClick ? () => onBandClick(page.p, bi) : undefined}
              style={{
                gridColumn: `${colStarts[bi] + 1} / span ${band.cols}`,
                gridRow: "1 / -1",
              } as CSSProperties}
            >
              {band.items.map((item, ii) => (
                <MatrixItemView
                  key={ii}
                  item={item}
                  flushRight={bi === 0 && item.c === band.cols - 1}
                  active={bookActive[ii]}
                />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MatrixItemView({
  item,
  flushRight,
  active,
}: {
  item: MatrixItem;
  flushRight: boolean;
  /** 书名联动高亮（仅 book 项使用） */
  active?: boolean;
}) {
  switch (item.kind) {
    case "large":
      return (
        <div
          className="m-large"
          style={
            {
              gridRow: `${item.r + 1} / span 2`,
              gridColumn: `${item.c + 1} / span 2`,
            } as CSSProperties
          }
        >
          {item.ch}
        </div>
      );
    case "circle":
      return (
        <div
          className="m-circle"
          style={
            {
              gridRow: `${item.r + 1} / span 2`,
              gridColumn: `${item.c + 1} / span 2`,
            } as CSSProperties
          }
        >
          <div className="m-ring">
            {[...item.text].length > 1 ? (
              <span className="stack">{item.text}</span>
            ) : (
              item.text
            )}
          </div>
        </div>
      );
    case "run":
      return (
        <div
          className="m-run"
          style={
            {
              gridRow: `${item.r + 1} / span ${item.cells.length}`,
              gridColumn: `${item.c + 1}`,
            } as CSSProperties
          }
        >
          {item.cells.map((ch, i) => (
            <div key={i} className="m-cell">
              {ch}
            </div>
          ))}
        </div>
      );
    case "book": {
      const openBottom = item.open === "bottom" || item.open === "both";
      const openTop = item.open === "top" || item.open === "both";
      const cls = [
        "m-book",
        openBottom && "open-bottom",
        openTop && "open-top",
        // 最右 band 最右列的书名与版框共线（复刻原 .line:first-child 规则意图）
        flushRight && "m-flush-r",
        active && "m-book-active",
      ]
        .filter(Boolean)
        .join(" ");
      return (
        <div
          className={cls}
          style={
            {
              gridRow: `${item.r + 1} / span ${item.cells.length}`,
              gridColumn: `${item.c + 1}`,
            } as CSSProperties
          }
        >
          {item.cells.map((ch, i) => (
            <div key={i} className="m-cell">
              {ch}
            </div>
          ))}
        </div>
      );
    }
  }
}
