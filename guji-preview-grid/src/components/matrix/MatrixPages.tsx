// Grid 矩阵渲染：MatrixPage[] → 严格字格矩阵 DOM
// 页 = 显式轨道 grid（1em 基准）；band（大行）= subgrid 项占满整页高，
// 其 border-left 即贯通界栏（data-rules 开关）；band 0（首个大行）放在最右列
import type { CSSProperties } from "react";
import type { MatrixItem, MatrixPage } from "@/matrix/types";

export function MatrixPages({
  pages,
  rules = true,
}: {
  pages: MatrixPage[];
  rules?: boolean;
}) {
  return (
    <div className="pages">
      {pages.map((pg, i) => (
        <MatrixPageView key={i} page={pg} rules={rules} />
      ))}
    </div>
  );
}

function MatrixPageView({ page, rules }: { page: MatrixPage; rules: boolean }) {
  // band 0 在最右：colStart = 排在其右侧的所有 band 宽度之和
  const colStarts: number[] = [];
  let acc = 0;
  for (let i = page.bands.length - 1; i >= 0; i--) {
    colStarts[i] = acc;
    acc += page.bands[i].cols;
  }
  const totalCols = Math.max(2, acc);

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
        {page.bands.map((band, bi) => (
          <div
            key={bi}
            className="m-band"
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
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function MatrixItemView({
  item,
  flushRight,
}: {
  item: MatrixItem;
  flushRight: boolean;
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
