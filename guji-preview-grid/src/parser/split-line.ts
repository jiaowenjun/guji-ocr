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
