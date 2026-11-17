// Kangxi semantic adapter for the dictionary UI.
import { kangxiEntries, type KangxiEntry } from "../../semantics/kangxi";
export type HeadwordCluster = KangxiEntry;
export const extractHeadwordClusters = kangxiEntries;

/** 字头词条文本：该组所在行行首 → 下一字头组所在行行首（无则页尾）。
 *  页内止——词条常延续到后页，只切本页部分；同一行多个字头组（未格式化稿）
 *  退化为该行行尾 */
export function headwordEntry(gj: string, cluster: HeadwordCluster): string {
  const lines = gj.split("\n");
  const all = extractHeadwordClusters(gj);
  const at = all.findIndex((c) => c.line === cluster.line && c.start === cluster.start);
  const next = at >= 0 ? all[at + 1] : undefined;
  // 末组取到页尾；同行多组（未格式化稿）退化为该行行尾
  const endLine = !next ? lines.length : next.line > cluster.line ? next.line : cluster.line + 1;
  return lines.slice(cluster.line, endLine).join("\n");
}

export type PageHeadwords =
  | { state: "loading" } // 当前页文本未就绪
  | { state: "own"; clusters: HeadwordCluster[] }
  | { state: "continuation"; fromPage: number; cluster: HeadwordCluster }
  | { state: "pending"; needPages: number[] } // 宿主候选页文本缺失，先取再算
  | { state: "none" }; // 回溯到清单头仍无字头（宿主不在已标注页内）

/** 判定一页的字头归属。current 用编辑缓冲（实时反映增删字头行），回溯只读已保存文本 */
export function resolvePageHeadwords(
  current: string | undefined,
  page: number,
  indexPages: number[],
  texts: Record<number, string>,
): PageHeadwords {
  if (current === undefined) return { state: "loading" };
  const clusters = extractHeadwordClusters(current);
  if (clusters.length > 0) return { state: "own", clusters };

  // 纯延续页：按清单序回溯（清单可能有洞，如缺 @329——序回溯天然跳过）。
  // 途中页文本缺失必须挂起等取：跳过未知页取更早的页可能选错宿主
  //（未知页自身可能持有真正的宿主字头）
  for (let i = indexPages.indexOf(page) - 1; i >= 0; i--) {
    const prev = indexPages[i];
    const text = texts[prev];
    if (text === undefined) return { state: "pending", needPages: [prev] };
    const prevClusters = extractHeadwordClusters(text);
    if (prevClusters.length > 0) {
      return { state: "continuation", fromPage: prev, cluster: prevClusters[prevClusters.length - 1] };
    }
  }
  return { state: "none" };
}
