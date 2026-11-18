/** 本地 API 的统一传输契约；业务步骤失败由响应字段表达。 */
export async function callPageTool<T>(body: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  const res = await fetch("/dataset/page-tool", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
    signal,
  });
  const data = await res.json().catch(() => ({})) as { ok?: boolean; error?: string };
  if (!res.ok || data.ok !== true) throw new Error(data.error ?? `HTTP ${res.status}`);
  return data as T;
}
