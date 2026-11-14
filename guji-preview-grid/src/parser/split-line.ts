// 移植自 vscode-guji-preview/src/parser/split-line.ts（行为保持一致）
// 【本仓库扩展】输入规范化（预处理，语义等同标准写法）：
//   1. 带圈字头的全角括号 → 半角：#（X）→#(X)、#（X→#(X
//   2. 带圈内容速记 → 汉字：z→增（补遗标）、数字→对应汉字（1→一、2→二…10→十、
//      11→十一…99→九十九，与带圈「(十五)」等书证标注对齐）
const DIGIT_MAP = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"];
function numberToCn(num: number): string | null {
  if (num < 0 || num > 99) return null;
  if (num < 10) return DIGIT_MAP[num];
  const tens = Math.floor(num / 10);
  const ones = num % 10;
  if (num < 20) return "十" + (ones ? DIGIT_MAP[ones] : "");
  return DIGIT_MAP[tens] + "十" + (ones ? DIGIT_MAP[ones] : "");
}
export function normalizeInput(text: string): string {
  const shorthand = (inner: string) =>
    inner.replace(/z/gi, "增").replace(/\d+/g, (d) => numberToCn(Number(d)) ?? d);
  return text
    // 全角括号 → 半角（保留可选闭括号；内容速记归一）
    .replace(/#（([^（）\n]{0,2})(）?)/g, (_m, inner: string, close: string) => `#(${shorthand(inner)}${close ? ")" : ""}`)
    // 半角括号内容速记归一（无速记则原样；闭括号保留）
    .replace(/#\(([^（）()\n]{0,2})(\)?)/g, (m, inner: string, close: string) =>
      /[zZ\d]/.test(inner) ? `#(${shorthand(inner)}${close}` : m,
    );
}

/** 糖带圈续写的全角括号 → 半角（语料无内容性全角括号；逐行应用以避开标题/注释） */
const halfwidthParens = (line: string) => line.replace(/（/g, "(").replace(/）/g, ")");

// ---- 字头簇扫描器（簇语法的单一事实源；formatGj 归一 / 字头条提取 / 编辑器高亮共用）----
//
// .gj 字头簇 = 大字 token 序 + 「古文」异体标注 + 、/： 胶水 + 尾部（半个「古」/注音冒号）。
// 糖语法（2026-11-14，与 gj2ir 词法镜像）：
//   - 带圈续写：簇内带圈 token 的 # 可省——#(五)#(增)#𠂂 ≡ #(五)(增)𠂂
//   - 裸字大写：带圈 token 后恰好一字（字头）、「古文」标记或 、 后（变体）可裸写——
//     #(三)#丹古文#𠁿#㣋 ≡ #(三)丹，古文：𠁿㣋（，：两侧可省）
//   - 普通 #X 后不可裸写（#丸俗… 的释义小字不受影响）；状态不跨行
//   - 行首「古文：」承接跨行异体（须带冒号——正文「古文酉」无冒号不误判）
// 标准形（formatGj 归一目标）：#(五)(增)𠂂、#(三)丹，古文：𠁿㣋——，：补全、
// 簇内冗余 # 删除、带圈括号补全；悬尾标记（变体在后续行，如 #丁古文）原样保留
export type HeadToken =
  /** 带圈 token（#(X)/#(X/(X)/(X；inner 为速记归一后内容） */
  | { kind: "circled"; inner: string; raw: string; start: number; end: number }
  /** 普通大字 #X */
  | { kind: "plain"; ch: string; raw: string; start: number; end: number }
  /** 裸字大字（糖：无 #） */
  | { kind: "bare"; ch: string; start: number; end: number }
  /** 「古文」异体标注（，?古文：?；行首承接形） */
  | { kind: "marker"; raw: string; start: number; end: number }
  /** 异体并列 、 */
  | { kind: "sep"; ch: string; start: number; end: number };

export interface HeadClusterMatch {
  tokens: HeadToken[];
  /** 尾部：跨 band 断开的半个「古」（#下古↵文#丅）与字头注音冒号（#丟:），原样保留 */
  tail: string;
  start: number;
  end: number;
}

const CIRCLED_HEAD = /^#[（(]([^()（）#\n]{1,2})[）)]?/u;
const CIRCLED_SUGAR = /^[（(]([^()（）#\n]{1,2})[）)]?/u;
const PLAIN_HEAD = /^#[^\s#【】()（）/]/u;
const MARKER_AFTER = /^，?古文[:：]?/u;
const MARKER_LEAD = /^古文[:：]/u;
const DUNHAO = /^、/u;
const CLUSTER_TAIL = /^(古文?)?[:：]?/u;

/** 裸字大写触发字符：内容字（CJK/ext-B 等），排除语法符、空白、标点、速记字母数字。
 *  gj2ir 与 parse-inline 的裸字判定共用此一口径 */
export const isBareLargeChar = (ch: string): boolean =>
  /^[^\s#【】()（）、。，：；！？·,.!?;'"《》*◎〇○a-zA-Z0-9]$/u.test(ch);

const shorthand = (inner: string) =>
  inner.replace(/z/gi, "增").replace(/\d+/g, (d) => numberToCn(Number(d)) ?? d);

/** 从 from 起扫描一个字头簇；无大字 token 返回 null（行首承接标记仅 from=0 认） */
export function scanHeadCluster(src: string, from = 0): HeadClusterMatch | null {
  const tokens: HeadToken[] = [];
  let i = from;
  let sawToken = false;
  let lastLarge: "circled" | "plain" | "bare" | null = null; // 上一个大字 token（标记/、置空）
  let variantMode = false; // 古文标记或 、 之后：裸字 = 异体变体

  while (i < src.length) {
    const rest = src.slice(i);
    let m: RegExpMatchArray | null;
    if (
      (m = MARKER_AFTER.exec(rest)) &&
      (lastLarge || (!sawToken && from === 0 && MARKER_LEAD.test(rest)))
    ) {
      tokens.push({ kind: "marker", raw: m[0], start: i, end: i + m[0].length });
      variantMode = true;
      lastLarge = null;
      i += m[0].length;
      continue;
    }
    if ((m = CIRCLED_HEAD.exec(rest))) {
      tokens.push({ kind: "circled", inner: shorthand(m[1]), raw: m[0], start: i, end: i + m[0].length });
      lastLarge = "circled";
      sawToken = true;
      i += m[0].length;
      continue;
    }
    if ((m = PLAIN_HEAD.exec(rest))) {
      tokens.push({ kind: "plain", ch: [...m[0]][1], raw: m[0], start: i, end: i + m[0].length });
      lastLarge = "plain";
      sawToken = true;
      i += m[0].length;
      continue;
    }
    // 糖：带圈续写 (Y)——大字 token 或标记/、 之后（含行首承接标记后）
    if ((m = CIRCLED_SUGAR.exec(rest)) && (lastLarge || variantMode)) {
      tokens.push({ kind: "circled", inner: shorthand(m[1]), raw: m[0], start: i, end: i + m[0].length });
      lastLarge = "circled";
      sawToken = true;
      i += m[0].length;
      continue;
    }
    // 糖：裸字大写——带圈 token 后（字头，一字）或标记/、 后（变体，连串）。
    // 无需 sawToken 前置：variantMode 只在簇内（标记/、后）为真，行首裸字不触发
    const one = [...rest][0];
    if (one !== undefined && isBareLargeChar(one) && (lastLarge === "circled" || variantMode)) {
      tokens.push({ kind: "bare", ch: one, start: i, end: i + one.length });
      lastLarge = "bare";
      sawToken = true;
      i += one.length;
      continue;
    }
    if (DUNHAO.test(rest) && sawToken && (lastLarge || variantMode)) {
      tokens.push({ kind: "sep", ch: "、", start: i, end: i + 1 });
      variantMode = true;
      lastLarge = null;
      i += 1;
      continue;
    }
    break;
  }
  if (!sawToken) return null;
  let tail = "";
  const tm = CLUSTER_TAIL.exec(src.slice(i));
  if (tm && tm[0].length > 0) {
    tail = tm[0];
    i += tm[0].length;
  }
  return { tokens, tail, start: from, end: i };
}

/** 扫描一行内全部字头簇（行内多组：#甲釋甲#乙釋乙） */
export function scanAllClusters(line: string): HeadClusterMatch[] {
  const out: HeadClusterMatch[] = [];
  let i = 0;
  while (i < line.length) {
    const cl = scanHeadCluster(line, i);
    if (cl) {
      out.push(cl);
      i = cl.end;
    } else i++;
  }
  return out;
}

/** 簇 → 标准形：首 token 保留 #，簇内合法裸写位置省 #；标记补全 ，：；
 *  悬尾标记（后无变体）原样；尾部原样。幂等：标准形再扫描再归一不变 */
export function canonicalCluster(cl: HeadClusterMatch): string {
  let out = "";
  let first = true;
  let prev: HeadToken["kind"] | null = null;
  let variantCtx = false; // 标记/、 之后：裸写合法（含 plain 拼写的变体，如 古文：#𠁿#㣋）
  for (const [k, t] of cl.tokens.entries()) {
    switch (t.kind) {
      case "circled":
        out += `${first ? "#" : ""}(${t.inner})`;
        break;
      case "plain": {
        // 裸写合法位置（带圈后 / 变体语境）省 #；#丶#宔 类保留
        const bare = !first && (prev === "circled" || variantCtx);
        out += bare ? t.ch : t.raw;
        break;
      }
      case "bare":
        out += t.ch;
        break;
      case "marker": {
        // 后随变体的标记 → 标准形补全（行首无逗号）；悬尾/跨行承接原样
        const hasVariants = cl.tokens
          .slice(k + 1)
          .some((x) => x.kind === "circled" || x.kind === "plain" || x.kind === "bare");
        out += !hasVariants ? t.raw : first ? "古文：" : "，古文：";
        break;
      }
      case "sep":
        out += t.ch;
        break;
    }
    prev = t.kind;
    if (t.kind === "marker" || t.kind === "sep") variantCtx = true;
    first = false;
  }
  return out + cl.tail;
}

// 【本仓库扩展】校对格式化（编辑器「格式化」按钮；不动字符流语义，只动源形排版）：
//   1. normalizeInput（全角括号/速记归一）
//   2. 字头簇归一为标准形：补全 #(X 右括号、省略簇内冗余 #、补全 ，古文： 标点
//   3. 字头组独占一行（对齐 @335 初校排版）：#A、#(A)、#A古文#B、#(A)#B、
//      #(三)中，古文：𠁧𠁩 …… 与前后释文断行。只插入折行，不增删空行（band 结构不变）
//   4. 首尾空行与注释行删除，EOF 归一为单个换行（中间的空行/注释不动）
export function formatGj(text: string): string {
  const lines = normalizeInput(text).split("\n").map((line) => {
    // 标题行（# 标题）与行内注释不参与
    if (/^\s*#+ /.test(line)) return line;
    const cut = line.indexOf("//");
    const src = halfwidthParens(cut >= 0 ? line.slice(0, cut) : line);
    const comment = cut >= 0 ? line.slice(cut) : "";
    let out = "";
    let last = 0;
    let afterCluster = false;
    for (const cl of scanAllClusters(src)) {
      // 断口两侧的空白修剪（解析时行首尾本会 trim，源文本直接写净）
      const between = src.slice(last, cl.start);
      out += `${afterCluster ? between.trim() : between.trimEnd()}\n${canonicalCluster(cl)}\n`;
      last = cl.end;
      afterCluster = true;
    }
    out += afterCluster ? src.slice(last).trimStart() : src.slice(last);
    return out.replace(/\n+/g, "\n").replace(/^\n|\n$/g, "") + comment;
  });
  // 首尾空行/注释行删除（中间不动）；EOF 归一为单个换行
  const blankish = (l: string) => {
    const t = l.trim();
    return t === "" || t.startsWith("//");
  };
  let s = 0;
  let e = lines.length;
  while (s < e && blankish(lines[s])) s++;
  while (e > s && blankish(lines[e - 1])) e--;
  const body = lines.slice(s, e).join("\n").replace(/[ \t]+$/, "");
  return body ? `${body}\n` : "";
}

export function split(text: string) {
  text = normalizeInput(text);
  let clean = text
    .replace(/[\s\S]*==.*/, "")
    .split(/\n/)
    .map((line) =>
      halfwidthParens(line)
        .replace(/　/g, "*")
        .trim()
        .replace(/[ \t]+/, " ")
    )
    .join("\n");
  return clean
    .split(/\n\s*\n/)
    .map((line) =>
      line
        .trim()
        .replace(/[。，·":：、《》]/g, "")
        .replace(/\/\/.*/, "")
        .replace(/[◎〇]/g, "○")
    )
    .filter((line) => line.length > 0);
}
