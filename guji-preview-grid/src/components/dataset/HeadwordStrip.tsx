// 字头条（工具栏下方窄条）：当前页字头字符一览；纯延续页显示回溯宿主字头。
// 只展示字形——字符用 GujiLarge（字头大字体）；字体缺字时依次回退：
// 站点扫描 SVG（/dataset/unencoded-svg/，映射由 link-dataset.sh 生成）→
// 系统字体 + 缺字描边。点击字头组弹窗展示详情（字形大样、码位、.gj 原文、
// 词条文本——own 态取编辑缓冲，延续态取宿主页已保存文本）。
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { headwordEntry, type HeadwordCluster, type PageHeadwords } from "@/components/dataset/headwords";

const EMPTY_SET = new Set<string>();

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

function ClusterCells({
  cluster,
  uncovered,
  svgMap,
  onOpen,
}: {
  cluster: HeadwordCluster;
  uncovered: Set<string>;
  svgMap: Record<string, string> | null;
  onOpen: (cluster: HeadwordCluster) => void;
}) {
  return (
    <button
      type="button"
      title={`字头详情：${cluster.raw}`}
      onClick={() => onOpen(cluster)}
      className="bg-background flex shrink-0 cursor-pointer items-center rounded-md border px-0.5 py-0.5 transition-colors hover:border-ring"
    >
      {cluster.chars.map((ch) => (
        <HeadwordChar key={ch + codepoint(ch)} ch={ch} missing={uncovered.has(ch)} svg={uncovered.has(ch) ? svgMap?.[ch] : undefined} />
      ))}
    </button>
  );
}

/** 字头详情弹窗内容（打开时快照——模态遮罩挡住编辑器，文本不会再变） */
interface HeadwordDetail {
  /** 词条来源页：own = 当前页，continuation = 宿主页 */
  page: number;
  cluster: HeadwordCluster;
  /** 词条 .gj 原文（来源页内部分，可能延续后页） */
  entry: string;
  /** 字形探测快照（缺字集合与 SVG 映射，与条内所见一致） */
  uncovered: Set<string>;
  svgMap: Record<string, string> | null;
}

function HeadwordDetailDialog({ detail, onClose }: { detail: HeadwordDetail; onClose: () => void }) {
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
          <span className="font-semibold">字头详情 · @{detail.page}</span>
          <Button size="sm" variant="ghost" onClick={onClose}>关闭</Button>
        </div>
        <div className="flex flex-wrap items-start gap-4 border-b pb-3">
          <div className="flex flex-wrap gap-2">
            {detail.cluster.chars.map((ch) => (
              <div key={ch + codepoint(ch)} className="flex flex-col items-center gap-1">
                <HeadwordChar ch={ch} missing={detail.uncovered.has(ch)} svg={detail.uncovered.has(ch) ? detail.svgMap?.[ch] : undefined} lg />
                <span className="text-muted-foreground font-mono text-[10px]">{codepoint(ch)}</span>
              </div>
            ))}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-muted-foreground mb-1 text-xs">.gj 字头组</div>
            <pre className="bg-muted w-fit max-w-full overflow-x-auto rounded px-2 py-1 font-mono text-xs whitespace-pre">{detail.cluster.raw}</pre>
          </div>
        </div>
        <div className="mt-3">
          <div className="text-muted-foreground mb-1 text-xs">词条（@{detail.page} 页内部分，可能延续后页）</div>
          <pre className="text-muted-foreground whitespace-pre-wrap font-mono text-xs leading-6">{detail.entry}</pre>
        </div>
      </div>
    </div>
  );
}

export function HeadwordStrip({
  resolved,
  page,
  text,
  texts,
}: {
  resolved: PageHeadwords;
  /** 当前页码与编辑缓冲（own 态词条来源，与 resolved 同源实时） */
  page?: number;
  text?: string;
  /** 各页已保存文本（continuation 态宿主页词条来源） */
  texts: Record<number, string>;
}) {
  const clusters = useMemo<HeadwordCluster[]>(() => {
    if (resolved.state === "own") return resolved.clusters;
    if (resolved.state === "continuation") return [resolved.cluster];
    return [];
  }, [resolved]);
  const allChars = useMemo(() => clusters.flatMap((c) => c.chars), [clusters]);
  const uncovered = useUncovered(allChars);
  const svgMap = useSvgMap(uncovered.size > 0);
  const [detail, setDetail] = useState<HeadwordDetail | null>(null);

  /** 词条来源与 resolved 同源：own = 当前页编辑缓冲，continuation = 宿主页已保存文本 */
  const openDetail = (cluster: HeadwordCluster) => {
    const cont = resolved.state === "continuation";
    const src = cont ? texts[resolved.fromPage] : text;
    const from = cont ? resolved.fromPage : page;
    if (src === undefined || from === undefined) return;
    setDetail({ page: from, cluster, entry: headwordEntry(src, cluster), uncovered, svgMap });
  };

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b px-3 py-1 text-xs">
        <span className="text-muted-foreground shrink-0">字头</span>
        {resolved.state === "loading" ? (
          <span className="text-muted-foreground">加载中…</span>
        ) : resolved.state === "pending" ? (
          <span className="text-muted-foreground">
            回溯宿主（取 {resolved.needPages.map((p) => `@${p}`).join(" ")}）…
          </span>
        ) : resolved.state === "none" ? (
          <span className="text-muted-foreground">无字头，宿主不在已标注页内</span>
        ) : (
          <>
            {resolved.state === "continuation" ? (
              <span className="shrink-0 text-amber-600" title="本页无字头，内容续入自该页的字头词条">
                续 @{resolved.fromPage} · 宿主
              </span>
            ) : null}
            {clusters.map((c, i) => (
              <ClusterCells key={`${i}-${c.raw}`} cluster={c} uncovered={uncovered} svgMap={svgMap} onOpen={openDetail} />
            ))}
          </>
        )}
      </div>
      {detail ? <HeadwordDetailDialog detail={detail} onClose={() => setDetail(null)} /> : null}
    </>
  );
}
