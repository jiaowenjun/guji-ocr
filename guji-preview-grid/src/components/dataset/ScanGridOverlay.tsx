import { useEffect, useState } from "react";
import type { L3Page } from "@/ir/layout3";
import type { PageEntry } from "./DatasetView";
import { scanGridPrior, type ScanGrid } from "./scan-grid";

// 只缓存本次会话里最近的布局；同一页换字但占格未变时无需重复测量。
const cache = new Map<string, ScanGrid>();

export function ScanGridOverlay({ entry, layout }: { entry: PageEntry; layout?: L3Page }) {
  let request = "";
  let layoutError = "";
  try {
    if (layout?.no === entry.page) request = JSON.stringify({ page: entry.page, spans: scanGridPrior(layout) });
  } catch (error) {
    layoutError = error instanceof Error ? error.message : String(error);
  }
  // 随定位算法修订失效，避免热更新后继续显示旧的版心错位结果。
  const key = `body-grid-v4-slanted:${entry.image}:${entry.width}:${entry.height}:${request}`;
  const [result, setResult] = useState<{ key: string; grid?: ScanGrid; error?: string } | null>(null);
  const [retry, setRetry] = useState(0);
  const grid = cache.get(key) ?? (result?.key === key ? result.grid : undefined);
  const error = layoutError || (result?.key === key ? result.error : undefined);

  useEffect(() => {
    if (!request || cache.has(key)) return;
    const controller = new AbortController();
    // 编辑时合并连续输入；切页或关闭立即取消，旧响应不会盖到新原图上。
    const timer = setTimeout(async () => {
      try {
        const response = await fetch("/dataset/scan-grid", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: request,
          signal: controller.signal,
        });
        const data = await response.json() as ScanGrid & { ok?: boolean; error?: string };
        if (!response.ok || data.ok !== true) throw new Error(data.error ?? `HTTP ${response.status}`);
        if (controller.signal.aborted) return;
        cache.set(key, data);
        if (cache.size > 24) cache.delete(cache.keys().next().value!);
        setResult({ key, grid: data });
      } catch (e) {
        if (!controller.signal.aborted) setResult({ key, error: e instanceof Error ? e.message : String(e) });
      }
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [request, key, retry]);

  if (grid) return <ScanGridLines grid={grid} />;
  return (
    <div className="absolute top-2 left-2 right-2 rounded bg-background/90 px-2 py-1 text-xs" role="status">
      {error ? `原图字格：${error}` : "正在定位原图字格…"}
      {error && !layoutError ? (
        <button className="ml-2 underline" onClick={() => { setResult(null); setRetry((v) => v + 1); }}>重试</button>
      ) : null}
    </div>
  );
}

/** 整列均匀投影所有网格线，包含空列/空格；不使用 region 或 glyph 候选框。 */
export function ScanGridLines({ grid }: { grid: ScanGrid }) {
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
          {Array.from({ length: 3 }, (_, col) => (
            <span key={`v${col}`} className={`scan-cell-rule scan-cell-rule-v${col % 2 ? " scan-cell-rule-minor" : ""}`}
              style={{ left: `${col / 2 * 100}%` }} />
          ))}
          {Array.from({ length: 25 }, (_, row) => (
            <span key={`h${row}`} className={`scan-cell-rule scan-cell-rule-h${row % 2 ? " scan-cell-rule-minor" : ""}`}
              style={{ top: `${row / 24 * 100}%` }} />
          ))}
        </div>
      ))}
    </div>
  );
}
