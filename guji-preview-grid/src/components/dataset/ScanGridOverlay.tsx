import type { PageCellRect, ScanGrid } from "./scan-grid";
import type { ScanGridState } from "./use-scan-grid";

export function ScanGridOverlay({ state, cells = true, active }: { state: ScanGridState; cells?: boolean; active?: PageCellRect | null }) {
  if (state.grid) return <ScanGridLines grid={state.grid} cells={cells} active={active} />;
  return <ScanGridStatus state={state} label={cells ? "原图字格" : "原图空格"} />;
}

export function ScanGridStatus({ state, label }: { state: ScanGridState; label: string }) {
  return (
    <div className="absolute top-2 left-2 right-2 rounded bg-background/90 px-2 py-1 text-xs" role="status">
      {state.error ? `${label}：${state.error}` : label === "原图字格" ? "正在定位原图字格…" : "正在识别原图空格…"}
      {state.canRetry ? <button className="ml-2 underline" onClick={state.retry}>重试</button> : null}
    </div>
  );
}

/** 整列均匀投影所有网格线，包含空列/空格；不使用 region 或 glyph 候选框。 */
export function ScanGridLines({ grid, cells = true, active }: { grid: ScanGrid; cells?: boolean; active?: PageCellRect | null }) {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" data-scan-grid aria-hidden="true">
      {grid.bands.map(([x1, y1, x2, y2], band) => (
        <div key={band} data-scan-band={band} className="absolute" style={{
          left: `${x1 / grid.width * 100}%`, top: `${y1 / grid.height * 100}%`,
          width: `${(x2 - x1) / grid.width * 100}%`, height: `${(y2 - y1) / grid.height * 100}%`,
        }}>
          {grid.blank_cells.filter((cell) => cell.band === band).map(({ col, row }) => (
            <span key={`blank-${col}-${row}`} data-scan-blank={`${band}:${col}:${row}`} className="scan-blank-cell"
              style={{ left: `${col / 2 * 100}%`, top: `${row / 24 * 100}%`, width: "50%", height: `${100 / 24}%` }} />
          ))}
          {cells && Array.from({ length: 3 }, (_, col) => (
            <span key={`v${col}`} className={`scan-cell-rule scan-cell-rule-v${col % 2 ? " scan-cell-rule-minor" : ""}`}
              style={{ left: `${col / 2 * 100}%` }} />
          ))}
          {cells && Array.from({ length: 25 }, (_, row) => (
            <span key={`h${row}`} className={`scan-cell-rule scan-cell-rule-h${row % 2 ? " scan-cell-rule-minor" : ""}`}
              style={{ top: `${row / 24 * 100}%` }} />
          ))}
          <ScanActiveCell active={active} band={band} />
        </div>
      ))}
    </div>
  );
}

/** 光标字格描边（与矩阵侧同款）：页面小格矩形 → 本大列内的局部列段；
 *  半格居中跨两列/大字 2×2 时合并为一个框，跨大列时各画各的。 */
function ScanActiveCell({ active, band }: { active?: PageCellRect | null; band: number }) {
  if (!active) return null;
  let localFirst = -1;
  let localLast = -1;
  for (let col = active.colStart; col < active.colEnd; col++) {
    if (7 - Math.floor(col / 2) !== band) continue;
    const local = col % 2;
    if (localFirst < 0 || local < localFirst) localFirst = local;
    if (local > localLast) localLast = local;
  }
  if (localFirst < 0) return null;
  return (
    <span data-scan-active={band} className="scan-char-active" style={{
      left: `${localFirst / 2 * 100}%`, width: `${(localLast - localFirst + 1) / 2 * 100}%`,
      top: `${active.rowStart / 24 * 100}%`, height: `${(active.rowEnd - active.rowStart) / 24 * 100}%`,
    }} />
  );
}
