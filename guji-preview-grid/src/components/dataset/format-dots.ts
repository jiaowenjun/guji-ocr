// .gj 圆点归一化（编辑器工具栏「格式化」按钮串联的纯函数之一）：
// 把爬取文本书名里的间隔号 •（U+2022 BULLET，如【易•乾卦】【周禮•夏官•槀人】）
// 规范化为语料标准写法 ·（U+00B7 MIDDLE DOT，如【易·繫辭】）。· 在渲染/评测
// 口径下本就被 GUJI_PROFILE 剔除，此转换只统一 .gj 源形，占格/换行/文本语义不变。
//
// 规则口径（与 format-circles 对齐）：
//   - • → ·（1:1，行内任意位置；语料现存 · 不动——仅转换非标准来源的 •）
//   - 标题行（#+空格）与 // 注释不动
export function formatDots(text: string): { text: string; count: number } {
  let count = 0;
  const out = text
    .split("\n")
    .map((line) => {
      if (/^\s*\/\//.test(line)) return line; // 整行注释
      if (/^\s*#+[ \t]/.test(line)) return line; // 标题行（语法空格）
      const ci = line.indexOf("//");
      const head = ci >= 0 ? line.slice(0, ci) : line;
      const tail = ci >= 0 ? line.slice(ci) : "";
      const next = head.replace(/•/g, () => {
        count += 1;
        return "·";
      });
      return next + tail;
    })
    .join("\n");
  return { text: out, count };
}
