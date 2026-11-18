// 爬取数据按页/码位查询本地 SQLite；查询本身不抓取，不依赖静态快照。
// 不保存模块级缓存：切页/重开弹窗读取当前库，编辑器重渲染不会重复请求。
import { useCallback, useEffect, useState } from "react";

/** 版本页位（同文書局本 / 武英殿本） */
export interface CrawlEdition {
  page: number;
  nth_char: number;
}

/** 爬取库词条 record（字段与演示页 api_entry 一致的子集） */
export interface CrawlEntryRecord {
  head: string;
  guwen: string | null;
  juan: string | null;
  unicode: string;
  radical: string;
  radical_strokes: number;
  extra_strokes: number;
  total_strokes: number;
  pinyin: string[];
  zhuyin: string[];
  cangjie: string | null;
  unihan: string | null;
  tongwen_edition: CrawlEdition | null;
  wuying_edition: CrawlEdition | null;
  text_paragraphs: string[];
  pua_other: string[];
}

/** 爬取库页字头索引条目（page_chars 行；char=null 为未编码 K 码字形，无详情端点） */
export interface CrawlPageHead {
  ord: number;
  char: string | null;
  /** Unicode 码位；未编码为 null */
  codepoint: number | null;
  k_code: string | null;
  svg: string | null;
  entry_no?: string | null;
}

type QueryResult<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: string };

const LOADING = { status: "loading" } as const;

/** 请求身份随参数或重试次数变化；取消后的响应不能覆盖当前页/当前字头。 */
function useCrawlQuery<T>(body: string | null) {
  const [attempt, setAttempt] = useState(0);
  const [snap, setSnap] = useState<{ body: string; attempt: number; result: QueryResult<T> } | null>(null);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  // 参数改变时即丢弃旧结果；快速切回原页也保持加载态，直到新查询完成。
  if (snap !== null && (snap.body !== body || snap.attempt !== attempt)) setSnap(null);
  useEffect(() => {
    if (body === null) return;
    const controller = new AbortController();
    fetch("/dataset/page-tool", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (res) => {
        const data = await res.json() as T & { ok?: boolean; error?: string };
        if (!res.ok || data.ok !== true) throw new Error(data.error ?? `HTTP ${res.status}`);
        if (!controller.signal.aborted) setSnap({ body, attempt, result: { status: "ready", data } });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setSnap({
          body, attempt,
          result: { status: "error", error: error instanceof Error ? error.message : String(error) },
        });
      });
    return () => controller.abort();
  }, [body, attempt]);
  const result = snap?.body === body && snap.attempt === attempt ? snap.result : LOADING;
  return { result, retry };
}

/** 弹窗每次打开查询单字全文；entry=null 表示库中未收录。 */
export function useCrawlEntry(head: string) {
  return useCrawlQuery<{ entry: CrawlEntryRecord | null }>(
    JSON.stringify({ action: "crawl-entry", codepoint: head.codePointAt(0) }),
  );
}

/** heads=null 表示尚未采集；[] 才是已采集但本页没有新字头。 */
export function useCrawlPageHeads(page: number | undefined) {
  return useCrawlQuery<{ heads: CrawlPageHead[] | null }>(
    page === undefined ? null : JSON.stringify({ action: "crawl-heads", page }),
  );
}
