// Guji (.gj) 语法高亮：规则移植自 vscode-guji-preview/syntaxes/guji.tmLanguage.json
// token 返回 StreamLanguage 内置 token 名（comment/keyword/heading/link/strong/...），
// 由 HighlightStyle 映射到具体颜色。
// 着色逻辑抽为纯函数 nextGujiToken（StreamLanguage 与 test/guji-language.spec 共用）；
// 字头簇（含糖写法）经 split-line 扫描器按行缓存定位。
import { HighlightStyle, StreamLanguage } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";
import { scanAllClusters, type HeadClusterMatch } from "../../parser/split-line";

export type GujiTokenName =
  | "comment"
  | "keyword"
  | "meta"
  | "heading"
  | "link"
  | "strong"
  | "escape";

// 字头簇（含糖写法）按行缓存：StreamLanguage 对同一行逐 token 回调，扫描器结果复用
let clusterCacheLine = "";
let clusterCache: HeadClusterMatch[] = [];
function clustersOf(line: string): HeadClusterMatch[] {
  if (line !== clusterCacheLine) {
    clusterCacheLine = line;
    clusterCache = scanAllClusters(line);
  }
  return clusterCache;
}

/** 行内着色分段（簇内 piece 平铺：token 边界即分段边界） */
function clusterPieces(cl: HeadClusterMatch): Array<{ start: number; end: number; tok: GujiTokenName }> {
  const pieces = cl.tokens.map((t) => ({
    start: t.start,
    end: t.end,
    tok: (t.kind === "marker" ? "keyword" : t.kind === "sep" ? "comment" : "strong") as GujiTokenName,
  }));
  if (cl.tail.length > 0) pieces.push({ start: cl.end - cl.tail.length, end: cl.end, tok: "comment" });
  return pieces;
}

/** 纯函数：line[pos..] 的下一个着色分段。返回推进位置与 token 名（null=普通文字）。
 *  只前向消费、无跨行状态——StreamLanguage 逐行调用，中途回放（编辑后重高亮）
 *  从任意 pos 复入结果一致 */
export function nextGujiToken(
  line: string,
  pos: number,
): { next: number; tok: GujiTokenName | null } {
  const rest = line.slice(pos);
  const atSol = pos === 0;

  if (atSol) {
    // 行注释（至行尾）
    if (/^\s*\/\//.test(rest)) return { next: line.length, tok: "comment" };
    // 页码声明 ^@\d+$
    if (/^\s*@\d+\s*$/.test(rest)) return { next: line.length, tok: "keyword" };
    // === 分隔条
    if (/^\s*=+$/.test(rest)) return { next: line.length, tok: "meta" };
    // 一行大字（标题）^#+ text
    if (/^\s*(#+) [^#【】]+\s*$/.test(rest)) return { next: line.length, tok: "heading" };
    // 跨行书名的后半段 ^text】（惰性匹配至首个 】）
    const bookEnd = rest.match(/^[^【】]+?】/);
    if (bookEnd) return { next: pos + bookEnd[0].length, tok: "link" };
  }

  // 行内注释
  if (rest.startsWith("//")) return { next: line.length, tok: "comment" };

  // 字头簇（含糖写法 #(五)(增)𠂂 / #(三)丹，古文：𠁿㣋，含全角括号/速记）：
  // 大字 token=strong、古文标记=keyword、胶水（、：，）与尾部（半个古/注音冒号）=comment
  const inCluster = clustersOf(line).find((c) => pos >= c.start && pos < c.end);
  if (inCluster) {
    const piece = clusterPieces(inCluster).find((p) => pos >= p.start && pos < p.end);
    if (piece) return { next: Math.max(pos + 1, piece.end), tok: piece.tok };
  }

  // 标点（渲染时会被剔除，按注释弱化显示）
  const punct = rest.match(/^[，。·•：:、《》]+/);
  if (punct) return { next: pos + punct[0].length, tok: "comment" };

  // 行内书名 【…】，或跨行书名的前半段（至行尾无 】）
  const book = rest.match(/^【([^【】]*)】?/);
  if (book && (book[0].endsWith("】") || book[0].length === rest.length)) {
    return { next: pos + book[0].length, tok: "link" };
  }

  // 兜底：扫描器不聚类的 # 大字（#　 空字格、#） 等语法 quirk——大字恒 strong。
  // 带圈 #(A) / #(AB) / #(A（u 标志：{1,2} 按码点计，代理对不被劈开）
  const circle = rest.match(/^#\([^)#【】]{1,2}\)?/u);
  if (circle) return { next: pos + circle[0].length, tok: "strong" };
  // 行内大字 #字（u 标志：字符类匹配整个码点——否则扩展 B 区字的高代理
  // 会被单独吞进 token，渲染成两个孤立代理的豆腐块）
  const large = rest.match(/^#[^#【】(]/u);
  if (large) return { next: pos + large[0].length, tok: "strong" };

  // 空格标记
  if (rest.startsWith("*") || rest.startsWith("　")) return { next: pos + 1, tok: "escape" };

  // 普通字符（单码点推进，代理对不被劈开）
  const cp = rest.codePointAt(0)!;
  return { next: pos + String.fromCodePoint(cp).length, tok: null };
}

export const gujiLanguage = StreamLanguage.define({
  name: "guji",
  token(stream) {
    const { next, tok } = nextGujiToken(stream.string, stream.pos);
    if (next <= stream.pos) stream.next(); // 防御：绝不原地踏步
    else stream.pos = next;
    return tok;
  },
  languageData: {
    commentTokens: { line: "//" },
  },
});

// 颜色经 CSS 变量引用（index.css 亮/暗两套 --guji-hl-*），随主题切换
export const gujiHighlight = HighlightStyle.define([
  { tag: t.comment, color: "var(--guji-hl-comment)", fontStyle: "italic" },
  { tag: t.keyword, color: "var(--guji-hl-keyword)", fontWeight: "600" },
  { tag: t.meta, color: "var(--guji-hl-comment)" },
  { tag: t.heading, color: "var(--guji-hl-heading)", fontWeight: "700" },
  { tag: t.strong, color: "var(--guji-hl-heading)", fontWeight: "600" },
  { tag: t.link, color: "var(--guji-hl-link)" },
  { tag: t.escape, color: "var(--guji-hl-escape)", fontStyle: "italic" },
]);
