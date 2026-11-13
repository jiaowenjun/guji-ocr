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

// 【本仓库扩展】校对格式化（编辑器「格式化」按钮；只动源文本排版，字符流不变）：
//   1. normalizeInput（全角括号/速记归一）
//   2. 未闭合带圈补右括号：#(X → #(X)
//   3. 字头组独占一行（对齐 @335 初校排版）：#A、#(A)、#A古文#B、#(A)#B、
//      #(三)#中古文#𠁧#𠁩 …… 与前后释文断行。只插入折行，不增删空行（band 结构不变）
//   4. 首尾空行与注释行删除，EOF 归一为单个换行（中间的空行/注释不动）
const HEAD_TOKEN = "#\\([^()（）#\\n]{1,2}\\)?|#[^\\s#【】()（）/]";
const HEAD_CLUSTER = new RegExp(
  `(?:${HEAD_TOKEN})(?:(?:古文)?(?:${HEAD_TOKEN}))*(?:古文)?`,
  "gu",
);
export function formatGj(text: string): string {
  const closed = normalizeInput(text).replace(
    /#\(([^()（）#\n]{1,2})(\)?)/g,
    (m, inner: string, close: string) => (close ? m : `#(${inner})`),
  );
  const lines = closed.split("\n").map((line) => {
      // 标题行（# 标题）与行内注释不参与
      if (/^\s*#+ /.test(line)) return line;
      const cut = line.indexOf("//");
      const src = cut >= 0 ? line.slice(0, cut) : line;
      const comment = cut >= 0 ? line.slice(cut) : "";
      let out = "";
      let last = 0;
      let afterCluster = false;
      for (const m of src.matchAll(HEAD_CLUSTER)) {
        // 断口两侧的空白修剪（解析时行首尾本会 trim，源文本直接写净）
        const between = src.slice(last, m.index);
        out += `${afterCluster ? between.trim() : between.trimEnd()}\n${m[0]}\n`;
        last = m.index + m[0].length;
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
      line
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
