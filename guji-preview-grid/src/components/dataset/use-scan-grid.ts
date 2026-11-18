import { useEffect, useState } from "react";
import type { L3Page } from "@/ir/layout3";
import type { PageEntry } from "./DatasetView";
import { scanGridPrior, type ScanGrid } from "./scan-grid";

// 只缓存本次会话里最近的布局；同一页换字但占格未变时无需重复测量。
const cache = new Map<string, ScanGrid>();

export function useScanGrid(entry: PageEntry | undefined, layout: L3Page | undefined, enabled: boolean) {
  let request = "";
  let layoutError = "";
  try {
    if (enabled && entry && layout?.no === entry.page) request = JSON.stringify({ page: entry.page, spans: scanGridPrior(layout) });
  } catch (error) {
    layoutError = error instanceof Error ? error.message : String(error);
  }
  // 随定位算法修订失效，避免热更新后继续显示旧的版心错位结果。
  const key = `body-grid-v4-slanted:${entry?.image}:${entry?.width}:${entry?.height}:${request}`;
  const [result, setResult] = useState<{ key: string; grid?: ScanGrid; error?: string } | null>(null);
  const [retry, setRetry] = useState(0);
  const grid = request ? cache.get(key) ?? (result?.key === key ? result.grid : undefined) : undefined;
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

  return {
    grid, error, canRetry: Boolean(error && !layoutError),
    retry: () => { setResult(null); setRetry((v) => v + 1); },
  };
}

export type ScanGridState = ReturnType<typeof useScanGrid>;
