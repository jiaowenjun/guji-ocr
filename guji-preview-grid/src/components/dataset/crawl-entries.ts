// 爬取词条详情（link-dataset.sh 从 tools/crawl 爬取库导出的 entries.json，
// 与爬取演示页「字头详情」同源同字段）：整条数字全文，与物理页界无关。
// 按码位键取——未编码字（k_code 无详情端点）与库缺录字头不在表内，
// 弹窗回退 .gj 页内文本并注明。
import { useEffect, useState } from "react";

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

export type CrawlEntries = Record<string, CrawlEntryRecord>;

/** 爬取库页字头索引条目（page_chars 行；char=null 为未编码 K 码字形，无详情端点） */
export interface CrawlPageHead {
  ord: number;
  char: string | null;
  /** 码位键（如 "200BF"）；未编码为 null */
  cp: string | null;
  k_code: string | null;
  svg: string | null;
  entry_no?: string | null;
}

/** 页码字符串 → 该页原始字头序（site page_chars 口径，与 .gj 无关） */
export type CrawlPageHeads = Record<string, CrawlPageHead[]>;

/** 字符 → 码位键（entries.json 键口径，如 "200BA"） */
export const cpKey = (ch: string) =>
  (ch.codePointAt(0) ?? 0).toString(16).toUpperCase().padStart(4, "0");

/** 模块级缓存盒（undefined = 未取过；null = 失败/缺文件），useLazyJson 专用 */
const entriesCacheBox: { v: CrawlEntries | null | undefined } = { v: undefined };
const pageHeadsCacheBox: { v: CrawlPageHeads | null | undefined } = { v: undefined };

/** 懒加载 JSON fixture（useSvgMap 同款模块缓存语义；url/box 均模块级稳定） */
function useLazyJson<T>(url: string, needed: boolean, box: { v: T | null | undefined }): T | null | undefined {
  const [snap, setSnap] = useState<T | null>(() => box.v ?? null);
  useEffect(() => {
    if (!needed || box.v !== undefined) return;
    let alive = true;
    fetch(url)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((m: T) => {
        box.v = m;
        if (alive) setSnap(m);
      })
      .catch(() => {
        box.v = null;
        if (alive) setSnap(null);
      });
    return () => {
      alive = false;
    };
  }, [needed]); // eslint-disable-line react-hooks/exhaustive-deps -- url/box 模块级常量
  return box.v !== undefined ? box.v : snap;
}

/** 爬取词条表（弹窗「爬取全文」区块，首次打开弹窗时拉取） */
export function useCrawlEntries(needed: boolean): CrawlEntries | null | undefined {
  return useLazyJson("/dataset/entries.json", needed, entriesCacheBox);
}

/** 逐页爬取原始字头表（字头栏「爬取」段，进页即拉取） */
export function useCrawlPageHeads(needed: boolean): CrawlPageHeads | null | undefined {
  return useLazyJson("/dataset/page-heads.json", needed, pageHeadsCacheBox);
}
