// .gj 〇格式化（编辑器工具栏「〇格式化」按钮的纯函数）：
// 把爬取文本带来的 ◎（U+25CE 双圈，按语标记「◎按《…」）规范化为语料标准写法
// 〇（U+3007）。渲染与评测口径下两者本就同归 ○（GUJI_PROFILE.normalize），
// 此转换只统一 .gj 源形，占格/换行/文本全不变。
//
// 规则口径（与 format-spaces 对齐）：
//   - ◎ → 〇（1:1，行内任意位置；语料现存 ○（319/320/324/328）与 〇（321/326）
//     不动——仅转换非标准来源的 ◎）
//   - 标题行（#+空格）与 // 注释不动：标题字符按原样入骨架、不经 normalize，
//     圈字符会字面渲染（语料标题亦无圈字符）
export function formatCircles(text: string): { text: string; count: number } {
  let count = 0;
  const out = text
    .split("\n")
    .map((line) => {
      if (/^\s*\/\//.test(line)) return line; // 整行注释
      if (/^\s*#+[ \t]/.test(line)) return line; // 标题行（语法空格）
      const ci = line.indexOf("//");
      const head = ci >= 0 ? line.slice(0, ci) : line;
      const tail = ci >= 0 ? line.slice(ci) : "";
      const next = head.replace(/◎/g, () => {
        count += 1;
        return "〇";
      });
      return next + tail;
    })
    .join("\n");
  return { text: out, count };
}
