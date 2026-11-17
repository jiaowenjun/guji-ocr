// .gj 侧页首跨页归属：判定「本页开头几行是上一页（或更早）字头词条的延续」。
// 页内判定复用 kangxiEntries——有大字的行才是字头行，页首全小字的延续段
// 天然不构成新字头；宿主按清单序回溯最近含字头页的最后一个词条。
import { kangxiEntries, kangxiHeading, type KangxiEntry } from "../../semantics/kangxi";

/** 页首延续段内容行号（0 基；跳过 @/分卷线/空行/注释，止于首个字头行
 *  （圆圈注记行回退为字头起点，不算延续）或首个标题行——先到者） */
export function openingContinuationLines(gj: string): number[] {
  const lines = gj.split("\n");
  const boundary = kangxiEntries(gj)[0]?.line ?? lines.length;
  const out: number[] = [];
  for (let li = 0; li < lines.length && li < boundary; li++) {
    const t = lines[li].trim();
    if (!t || t.startsWith("//") || /^@\d+$|^=+$/.test(t)) continue;
    if (kangxiHeading(lines[li])) break; // 标题行是卷/部边界，此前不该有内容行
    out.push(li);
  }
  return out;
}

export type PageContinuation =
  | { state: "pending"; needPages: number[] } // 宿主候选页文本缺失，先取再算
  | { state: "host"; fromPage: number; cluster: KangxiEntry; lines: number[] }
  | { state: "none"; lines: number[] }; // 有延续行但回溯到清单头仍无字头（宿主不在已标注页内）

/** 判定当前页页首延续段的宿主词条。current 用编辑缓冲（实时反映增删字头行），
 *  回溯只读传入文本表；返回 null = 无延续段或文本未就绪 */
export function resolvePageContinuation(
  current: string | undefined,
  page: number,
  indexPages: number[],
  texts: Record<number, string>,
): PageContinuation | null {
  if (current === undefined) return null;
  const lines = openingContinuationLines(current);
  if (lines.length === 0) return null;
  // 按清单序回溯（清单可有洞，如缺 @329——序回溯天然跳过；无页数上限，
  // 中间页全为纯延续页时可一路回溯到「上几页」）。途中页文本缺失必须挂起
  // 等取：跳过未知页取更早的页可能选错宿主（未知页自身可能持有真宿主字头）
  for (let i = indexPages.indexOf(page) - 1; i >= 0; i--) {
    const prev = indexPages[i];
    const text = texts[prev];
    if (text === undefined) return { state: "pending", needPages: [prev] };
    const clusters = kangxiEntries(text);
    if (clusters.length > 0)
      return { state: "host", fromPage: prev, cluster: clusters[clusters.length - 1], lines };
  }
  return { state: "none", lines };
}
