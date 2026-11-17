// 字头段（并入工具栏单行，嵌在界栏/字格开关之后）：只显爬取库该页
// 原始字头序（page-heads.json，site page_chars 口径，含未编码 K 码字形）。
// 点击弹窗也只显爬取侧（字形大样、码位、词条全文——entries.json 同源
// 爬取库，与爬取演示页字段一致），不带任何 .gj 侧内容。
// 段首另显 .gj 侧页首跨页归属徽标（continuation）：本页开头几行是
// 哪一页字头词条的延续，点击宿主字头弹爬取详情。
// 字形用 GujiLarge（字头大字体）；缺字时依次回退：站点扫描 SVG
// （/dataset/unencoded-svg/）→ 系统字体 + 缺字描边。
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { cpKey, useCrawlEntries, useCrawlPageHeads, type CrawlEdition, type CrawlEntries, type CrawlEntryRecord, type CrawlPageHead } from "@/components/dataset/crawl-entries";
import { type PageContinuation } from "@/components/dataset/headwords";

const EMPTY_SET = new Set<string>();
const EMPTY_HEADS: CrawlPageHead[] = [];

/** GujiLarge 加载后逐字 check 出的缺字集合；加载失败不判缺字（避免误切 SVG）。
 *  结果带 key 快照存回——字符集变化即回到「未探测」，不在 effect 里同步重置 */
function useUncovered(chars: string[]): Set<string> {
  const key = chars.join("\u0000");
  const [snap, setSnap] = useState<{ key: string; uncovered: Set<string> }>({
    key: "",
    uncovered: EMPTY_SET,
  });
  useEffect(() => {
    if (!key) return;
    let alive = true;
    (async () => {
      const uniq = [...new Set(key.split("\u0000"))];
      try {
        await document.fonts.load("48px GujiLarge", uniq.join(""));
        if (!alive) return;
        const bad = uniq.filter((ch) => !document.fonts.check("48px GujiLarge", ch));
        setSnap({ key, uncovered: new Set(bad) });
      } catch {
        /* 字体不可用：按字符渲染，不判缺字 */
      }
    })();
    return () => {
      alive = false;
    };
  }, [key]);
  return snap.key === key ? snap.uncovered : EMPTY_SET;
}

/** 缺字 → 站点扫描 SVG 文件名映射；仅在出现缺字时拉取（失败静默为空映射） */
let svgMapCache: Record<string, string> | null | undefined; // undefined = 未取过
function useSvgMap(needed: boolean): Record<string, string> | null {
  const [map, setMap] = useState<Record<string, string> | null>(() => svgMapCache ?? null);
  useEffect(() => {
    if (!needed || svgMapCache !== undefined) return;
    let alive = true;
    fetch("/dataset/headword-svg.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((m: Record<string, string>) => {
        svgMapCache = m;
        if (alive) setMap(m);
      })
      .catch(() => {
        svgMapCache = {};
        if (alive) setMap(svgMapCache);
      });
    return () => {
      alive = false;
    };
  }, [needed]);
  return map;
}

const codepoint = (ch: string) =>
  "U+" + (ch.codePointAt(0) ?? 0).toString(16).toUpperCase().padStart(4, "0");

/** 延续段行号（0 基）→ 1 基展示（第 2 行 / 第 2–4 行） */
const lineRange = (lines: number[]) => {
  const a = lines[0] + 1;
  const b = lines[lines.length - 1] + 1;
  return a === b ? `第 ${a} 行` : `第 ${a}–${b} 行`;
};

/** 单个字头字符格：GujiLarge → 站点 SVG → 系统字体 + 缺字描边（条内小格 / 弹窗大样） */
function HeadwordChar({
  ch,
  missing,
  svg,
  lg = false,
}: {
  ch: string;
  missing: boolean;
  svg?: string;
  lg?: boolean;
}) {
  return (
    <span
      title={`${ch}（${codepoint(ch)}）${missing ? " · GujiLarge 缺字" : ""}`}
      className={`hw-char${lg ? " hw-char-lg" : ""} ${missing && !svg ? "hw-char-missing" : ""}`}
    >
      {missing ? (svg ? <img src={`/dataset/unencoded-svg/${svg}`} alt={ch} draggable={false} /> : ch) : ch}
    </span>
  );
}

/** 单个字头格：点击弹爬取侧详情 */
function CrawlHeadCells({
  ch,
  missing,
  svg,
  onOpen,
}: {
  ch: string;
  missing: boolean;
  svg?: string;
  onOpen: (ch: string) => void;
}) {
  return (
    <button
      type="button"
      title={`爬取字头详情：${ch}`}
      onClick={() => onOpen(ch)}
      className="bg-background flex shrink-0 cursor-pointer items-center rounded-md border border-dashed px-0.5 py-0.5 transition-colors hover:border-ring"
    >
      <HeadwordChar ch={ch} missing={missing} svg={missing ? svg : undefined} />
    </button>
  );
}

/** 字头详情弹窗内容（打开时快照——模态遮罩挡住编辑器） */
interface HeadwordDetail {
  page: number;
  /** 字头字符 */
  head: string;
  /** 字形探测快照（缺字集合与 SVG 映射，与条内所见一致） */
  uncovered: Set<string>;
  svgMap: Record<string, string> | null;
}
/** 爬取词条 record 展示（字段与爬取演示页「字头详情」卡片一致） */
function CrawlRecordSection({ rec }: { rec: CrawlEntryRecord }) {
  const edition = (name: string, e: CrawlEdition | null) =>
    e ? `${name}第 ${e.page} 頁，第 ${e.nth_char} 字` : null;
  const editions = [edition("同文書局本", rec.tongwen_edition), edition("武英殿本", rec.wuying_edition)]
    .filter(Boolean)
    .join("；");
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="text-base font-semibold">{rec.head}</span>
        {rec.guwen ? <span className="text-xs">古文 {rec.guwen}</span> : null}
        {rec.juan ? <span className="text-muted-foreground text-xs">{rec.juan}</span> : null}
        <code className="text-muted-foreground text-[10px]">{rec.unicode}</code>
      </div>
      <table className="w-full border-collapse text-xs">
        <tbody>
          <tr>
            <td className="text-muted-foreground w-24 border-b border-dashed py-0.5 pr-2 whitespace-nowrap align-top">部首</td>
            <td className="border-b border-dashed py-0.5">
              {rec.radical}（部首 {rec.radical_strokes} 畫，部外 {rec.extra_strokes} 畫，共 {rec.total_strokes} 畫）
            </td>
          </tr>
          <tr>
            <td className="text-muted-foreground w-24 border-b border-dashed py-0.5 pr-2 whitespace-nowrap align-top">拼音 / 注音</td>
            <td className="border-b border-dashed py-0.5">
              {rec.pinyin.join("，") || "—"} ／ {rec.zhuyin.join("，") || "—"}
            </td>
          </tr>
          <tr>
            <td className="text-muted-foreground w-24 border-b border-dashed py-0.5 pr-2 whitespace-nowrap align-top">倉頡 · 統一碼</td>
            <td className="border-b border-dashed py-0.5">{rec.cangjie ?? "—"} · {rec.unihan ?? "—"}</td>
          </tr>
          {editions ? (
            <tr>
              <td className="text-muted-foreground w-24 py-0.5 pr-2 whitespace-nowrap align-top">版本頁位</td>
              <td className="py-0.5">{editions}</td>
            </tr>
          ) : null}
        </tbody>
      </table>
      <pre className="whitespace-pre-wrap text-xs leading-6">{rec.text_paragraphs.join("\n")}</pre>
      {rec.pua_other.length > 0 ? (
        <div className="text-xs text-amber-600">
          ⚠ 释文含疑似 kxfont 字形的私用区字符：{rec.pua_other.join(" ")}，需人工定字
        </div>
      ) : null}
    </div>
  );
}

/** 取爬取词条；未收录者注明 */
function CrawlRecordsSection({ crawl, chars }: { crawl: CrawlEntries; chars: string[] }) {
  const records = chars
    .map((ch) => crawl[cpKey(ch)])
    .filter((r): r is CrawlEntryRecord => Boolean(r));
  if (records.length === 0) {
    return (
      <div className="text-muted-foreground text-xs">
        爬取库未收录此字头（未编码字形无详情端点，或库缺录）
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {records.map((rec) => (
        <CrawlRecordSection key={rec.unicode} rec={rec} />
      ))}
    </div>
  );
}

function HeadwordDetailDialog({
  detail,
  crawl,
  onClose,
}: {
  detail: HeadwordDetail;
  /** 爬取词条表（useCrawlEntries 直传：异步取到后弹窗内即时补显） */
  crawl: CrawlEntries | null | undefined;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-6"
      onClick={onClose}
    >
      <div
        className="bg-background text-foreground max-h-[80vh] w-[620px] max-w-[90vw] overflow-auto rounded-lg border p-4 text-sm shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <span className="font-semibold">爬取字头详情 · @{detail.page}</span>
          <Button size="sm" variant="ghost" onClick={onClose}>关闭</Button>
        </div>
        <div className="flex flex-wrap items-start gap-4 border-b pb-3">
          <div className="flex flex-col items-center gap-1">
            <HeadwordChar ch={detail.head} missing={detail.uncovered.has(detail.head)} svg={detail.uncovered.has(detail.head) ? detail.svgMap?.[detail.head] : undefined} lg />
            <span className="text-muted-foreground font-mono text-[10px]">{codepoint(detail.head)}</span>
          </div>
        </div>
        <div className="mt-3">
          <div className="text-muted-foreground mb-1 text-xs">爬取全文（kangxizidian.com 词条详情，整条与页界无关）</div>
          {crawl === undefined ? (
            <div className="text-muted-foreground text-xs">加载中…</div>
          ) : crawl === null ? (
            <div className="text-muted-foreground text-xs">entries.json 不可用（未生成或加载失败），爬取侧不可显示</div>
          ) : (
            <CrawlRecordsSection crawl={crawl} chars={[detail.head]} />
          )}
        </div>
      </div>
    </div>
  );
}

export function HeadwordStrip({
  page,
  continuation,
  crawlEpoch = 0,
}: {
  page?: number;
  continuation?: PageContinuation | null;
  /** 加页后 +1：add 已随写 fixture，重取覆盖模块缓存（不动编辑缓冲） */
  crawlEpoch?: number;
}) {
  /** 爬取库当前页原始字头（site page_chars 口径；null=fixture 不可用，undefined=加载中） */
  const crawlHeads = useCrawlPageHeads(page !== undefined, crawlEpoch);
  const crawled = useMemo(
    () => (page !== undefined && crawlHeads ? crawlHeads[String(page)] ?? [] : undefined),
    [page, crawlHeads],
  );
  /** 条内渲染用（未就绪分支各自显提示，此值仅在就绪分支使用） */
  const heads = crawled ?? EMPTY_HEADS;
  /** 宿主字头一并探测缺字（延续徽标与字头格同套 GujiLarge/SVG 兜底） */
  const allChars = useMemo(() => {
    const chars = heads.map((h) => h.char ?? "").filter(Boolean);
    if (continuation?.state === "host") chars.push(continuation.cluster.head);
    return chars;
  }, [heads, continuation]);
  const uncovered = useUncovered(allChars);
  const svgMap = useSvgMap(uncovered.size > 0);
  const [detail, setDetail] = useState<HeadwordDetail | null>(null);
  const crawl = useCrawlEntries(detail !== null, crawlEpoch);

  /** 字头格点击：弹爬取侧详情（字形大样 + 词条全文） */
  const openHead = (ch: string) => {
    if (page === undefined) return;
    setDetail({ page, head: ch, uncovered, svgMap });
  };

  /** 延续徽标点击：弹宿主字头的爬取详情（词条全文与页界无关，天然含本页延续段） */
  const openHost = () => {
    if (continuation?.state !== "host") return;
    const { fromPage, cluster } = continuation;
    setDetail({ page: fromPage, head: cluster.head, uncovered, svgMap });
  };

  /** host 徽标悬浮详情：延续行数 + 行号范围 + 宿主词条（含古文变体） */
  const host = continuation?.state === "host" ? continuation : undefined;
  const hostTitle = host
    ? `本页开头 ${host.lines.length} 行（${lineRange(host.lines)}）是 @${host.fromPage}「${host.cluster.head}」词条的延续` +
      (host.cluster.chars.length > 1
        ? `（含古文 ${host.cluster.chars.filter((c) => c !== host.cluster.head).join("")}）`
        : "")
    : undefined;

  return (
    <>
      {/* 无边框内联段：作为工具栏 flex 行的一个子项，字头多时自行换行 */}
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        {/* .gj 侧页首跨页归属（不依赖爬取 fixture）：宿主字头可点击弹爬取详情 */}
        {host ? (
          <button
            type="button"
            title={hostTitle}
            onClick={openHost}
            className="bg-background flex shrink-0 cursor-pointer items-center gap-1 rounded-md border px-1 py-0.5 transition-colors hover:border-ring"
          >
            <span className="text-muted-foreground shrink-0">@{host.fromPage} ↩</span>
            <HeadwordChar
              ch={host.cluster.head}
              missing={uncovered.has(host.cluster.head)}
              svg={uncovered.has(host.cluster.head) ? svgMap?.[host.cluster.head] : undefined}
            />
            <span className="text-muted-foreground shrink-0">{host.lines.length} 行</span>
          </button>
        ) : continuation ? (
          <span
            className="text-muted-foreground shrink-0"
            title={
              continuation.state === "pending"
                ? "宿主候选页文本未就绪，补取后自动判定（不跳过未知页，防选错宿主）"
                : `本页开头 ${continuation.lines.length} 行（${lineRange(continuation.lines)}）延续，但清单内更早页均无字头——宿主可能不在已标注页内`
            }
          >
            ↩ {continuation.lines.length} 行延续
            {continuation.state === "pending" ? " · 前页取文中…" : " · 宿主不在清单"}
          </span>
        ) : null}
        {page === undefined ? null : crawlHeads === undefined ? (
          <span className="text-muted-foreground">字头加载中…</span>
        ) : crawlHeads === null ? (
          <span className="text-muted-foreground">page-heads.json 不可用（未生成或加载失败）</span>
        ) : (
          <>
            <span
              className="text-muted-foreground shrink-0"
              title={`爬取库该页原始字头 ${heads.length} 个（site page_chars 口径，含未编码 K 码字形）`}
            >
              爬取 {heads.length}
            </span>
            {heads.map((h) =>
              h.char ? (
                <CrawlHeadCells
                  key={`${h.cp}-${h.char}`}
                  ch={h.char}
                  missing={uncovered.has(h.char)}
                  svg={svgMap?.[h.char]}
                  onOpen={openHead}
                />
              ) : (
                <span
                  key={h.svg ?? h.k_code ?? "?"}
                  title={`未编码字形 ${h.k_code}（无详情端点，灰显不可查）`}
                  className="flex shrink-0 items-center rounded-md border border-dashed opacity-80"
                >
                  <span className="hw-char">
                    {h.svg ? (
                      // head-svg = WD-2T 随爬缓存，相对路径直拼（0000s/…）；
                      // 仍缺（未挂载/回补未及）时破图回退 □
                      <img
                        src={`/dataset/head-svg/${h.svg}`}
                        alt={h.k_code ?? "□"}
                        draggable={false}
                        onError={(e) => {
                          e.currentTarget.outerHTML = "□";
                        }}
                      />
                    ) : (
                      "□"
                    )}
                  </span>
                </span>
              ),
            )}
          </>
        )}
      </div>
      {detail ? <HeadwordDetailDialog detail={detail} crawl={crawl} onClose={() => setDetail(null)} /> : null}
    </>
  );
}
