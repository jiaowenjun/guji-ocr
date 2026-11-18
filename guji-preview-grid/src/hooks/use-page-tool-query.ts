import { useCallback, useEffect, useState } from "react";
import { callPageTool } from "@/lib/page-tool";

type QueryResult<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: string };

const LOADING = { status: "loading" } as const;

/** 请求身份随参数或重试次数变化；取消后的响应不能覆盖当前页/当前字头。 */
export function usePageToolQuery<T>(body: string | null, refresh = 0) {
  const [attempt, setAttempt] = useState(0);
  const [snap, setSnap] = useState<{ body: string; attempt: number; refresh: number; result: QueryResult<T> } | null>(null);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  // 参数改变时即丢弃旧结果；快速切回原页也保持加载态，直到新查询完成。
  if (snap !== null && (snap.body !== body || snap.attempt !== attempt || snap.refresh !== refresh)) setSnap(null);
  useEffect(() => {
    if (body === null) return;
    const controller = new AbortController();
    callPageTool<T>(JSON.parse(body), controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setSnap({ body, attempt, refresh, result: { status: "ready", data } });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setSnap({
          body, attempt, refresh,
          result: { status: "error", error: error instanceof Error ? error.message : String(error) },
        });
      });
    return () => controller.abort();
  }, [body, attempt, refresh]);
  const result = snap?.body === body && snap.attempt === attempt && snap.refresh === refresh ? snap.result : LOADING;
  return { result, retry };
}
