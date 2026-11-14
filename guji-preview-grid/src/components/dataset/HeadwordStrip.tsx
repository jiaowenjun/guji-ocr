// 字头条（工具栏下方窄条）：当前页字头字符一览；纯延续页显示回溯宿主字头。
// 只展示字形——字符用 GujiLarge（字头大字体）；字体缺字时依次回退：
// 站点扫描 SVG（/dataset/unencoded-svg/，映射由 link-dataset.sh 生成）→
// 系统字体 + 缺字描边。字头详情（音义等）不在本条范围。
import { useEffect, useMemo, useState } from "react";
import type { HeadwordCluster, PageHeadwords } from "@/components/dataset/headwords";

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

function ClusterCells({
  cluster,
  uncovered,
  svgMap,
}: {
  cluster: HeadwordCluster;
  uncovered: Set<string>;
  svgMap: Record<string, string> | null;
}) {
  return (
    <span
      title={cluster.raw}
      className="bg-background flex shrink-0 items-center rounded-md border px-0.5 py-0.5"
    >
      {cluster.chars.map((ch) => {
        const missing = uncovered.has(ch);
        const svg = missing ? svgMap?.[ch] : undefined;
        return (
          <span
            key={ch + codepoint(ch)}
            title={`${ch}（${codepoint(ch)}）${missing ? " · GujiLarge 缺字" : ""}`}
            className={`hw-char ${missing && !svg ? "hw-char-missing" : ""}`}
          >
            {missing ? (svg ? <img src={`/dataset/unencoded-svg/${svg}`} alt={ch} draggable={false} /> : ch) : ch}
          </span>
        );
      })}
    </span>
  );
}

export function HeadwordStrip({ resolved }: { resolved: PageHeadwords }) {
  const clusters = useMemo<HeadwordCluster[]>(() => {
    if (resolved.state === "own") return resolved.clusters;
    if (resolved.state === "continuation") return [resolved.cluster];
    return [];
  }, [resolved]);
  const allChars = useMemo(() => clusters.flatMap((c) => c.chars), [clusters]);
  const uncovered = useUncovered(allChars);
  const svgMap = useSvgMap(uncovered.size > 0);

  return (
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
            <ClusterCells key={`${i}-${c.raw}`} cluster={c} uncovered={uncovered} svgMap={svgMap} />
          ))}
        </>
      )}
    </div>
  );
}
