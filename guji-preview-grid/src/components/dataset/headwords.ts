// 页面字头解析（字头条展示用，纯逻辑）：
//   - 提取：逐行复用 formatGj 的 HEAD_CLUSTER（与「字头组独占一行」同一事实源），
//     只保留字头字符——#(增)/#(三) 等圈号标记（补遗/页位次）不是字头字符，丢弃
//   - 归属：本页无字头 = 纯延续页，按清单序回溯最近一个有字头的页，取其最后一组
//     为宿主（与 前页续入回放验证 的跨页回溯链语义一致，@332/@333 → @331「中」）
import { HEAD_CLUSTER, HEAD_TOKEN } from "@/parser/split-line";

export interface HeadwordCluster {
  /** .gj 原文（含标记/古文/冒号，tooltip 展示用） */
  raw: string;
  /** 字头字符（主字头 + 古文/异体变体，序即版面序） */
  chars: string[];
}

const TOKEN_RE = new RegExp(HEAD_TOKEN, "gu");

/** 提取一页 .gj 内全部字头组；标题行/@页码/注释不参与（口径同 formatGj） */
export function extractHeadwordClusters(gj: string): HeadwordCluster[] {
  const out: HeadwordCluster[] = [];
  for (const line of gj.split("\n")) {
    if (/^\s*#+ /.test(line) || /^@\d+\s*$/.test(line)) continue;
    const cut = line.indexOf("//");
    const src = cut >= 0 ? line.slice(0, cut) : line;
    for (const m of src.matchAll(HEAD_CLUSTER)) {
      const chars = [...m[0].matchAll(TOKEN_RE)]
        .map((t) => t[0])
        .filter((t) => !t.startsWith("#(")) // 圈号标记非字头字符
        .map((t) => t.slice(1)); // 去 # 前缀（u 标志下单码点，slice 兼容代理对）
      if (chars.length > 0) out.push({ raw: m[0], chars });
    }
  }
  return out;
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
