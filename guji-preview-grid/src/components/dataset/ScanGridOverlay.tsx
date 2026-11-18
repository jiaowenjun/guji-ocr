import type { ScanGrid } from "./scan-grid";
import type { ScanGridState } from "./use-scan-grid";

export function ScanGridOverlay({ state, cells = true }: { state: ScanGridState; cells?: boolean }) {
  if (state.grid) return <ScanGridLines grid={state.grid} cells={cells} />;
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
export function ScanGridLines({ grid, cells = true }: { grid: ScanGrid; cells?: boolean }) {
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
        </div>
      ))}
    </div>
  );
}
