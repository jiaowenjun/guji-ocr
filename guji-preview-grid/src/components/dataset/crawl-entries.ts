import { usePageToolQuery } from "@/hooks/use-page-tool-query";
// 爬取数据按页/码位查询本地 SQLite；查询本身不抓取，不依赖静态快照。
// 不保存模块级缓存：切页/重开弹窗读取当前库，编辑器重渲染不会重复请求。

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

/** 弹窗每次打开查询单字全文；entry=null 表示库中未收录。 */
export function useCrawlEntry(head: string) {
  return usePageToolQuery<{ entry: CrawlEntryRecord | null }>(
    JSON.stringify({ action: "crawl-entry", codepoint: head.codePointAt(0) }),
  );
}

/** heads=null 表示尚未采集；[] 才是已采集但本页没有新字头。 */
export function useCrawlPageHeads(page: number | undefined) {
  return usePageToolQuery<{ heads: CrawlPageHead[] | null }>(
    page === undefined ? null : JSON.stringify({ action: "crawl-heads", page }),
  );
}

/** 字体缺字时查询当前身份映射及已缓存 SVG，失败可重试。 */
export function useCrawlGlyphs(chars: Set<string>) {
  return usePageToolQuery<{ glyphs: Record<string, string> }>(
    chars.size ? JSON.stringify({ action: "crawl-glyphs", codepoints: [...chars].map(ch => ch.codePointAt(0)).sort() }) : null,
  );
}
