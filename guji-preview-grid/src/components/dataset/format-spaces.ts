// .gj 空格格式化（编辑器工具栏「空格格式化」按钮的纯函数）：
// 把「渲染上恰为一个空字格」的行内空格改写为显式 *，让占格在源码层面可见，
// 且不再受 lineTransform 的 trim / 折叠影响（语料惯例：312–328 校对页全用 *）。
//
// 等价口径（对齐 gj2ir/parseInline 消费的 lineTransform：　→* → trim → 折叠首个半角串）：
//   - 全角空格 　 → *（1:1，任何位置。lineTransform 本就先做 　→* 再 trim，逐格等价）
//   - 行内半角空格/tab 连续串 → 单个 *（首个串渲染时本就折叠为 1 格；分隔符惯例 = 1 个 *）
//   - 行首/行尾半角空格不动：trim 本会删掉它们（不占格），写成 * 反而凭空多出空字格
//   - 标题行（#+ 后跟空格/tab）整行不动：#+ 后的空格是标题语法分隔符（^(#+) (.*)$）；
//     且标题字符按原样入骨架（gj2ir 标题分支无 *→空格 映射），行内 * 会渲染成字面星号
//   - 注释不动：整行 // 与行内 // 尾注均不参与渲染
export function formatSpaces(text: string): { text: string; count: number } {
  let count = 0;
  const out = text
    .split("\n")
    .map((line) => {
      if (/^\s*\/\//.test(line)) return line; // 整行注释
      if (/^\s*#+[ \t]/.test(line)) return line; // 标题行（语法空格）
      const ci = line.indexOf("//");
      const head = ci >= 0 ? line.slice(0, ci) : line;
      const tail = ci >= 0 ? line.slice(ci) : "";
      const full = head.replace(/　/g, () => {
        count += 1;
        return "*";
      });
      // 行内半角串：两侧必须是非空格/tab 字符（行首/行尾的不动）
      const half = full.replace(/([^ \t])[ \t]+(?=[^ \t])/g, (_m, lead: string) => {
        count += 1;
        return lead + "*";
      });
      return half + tail;
    })
    .join("\n");
  return { text: out, count };
}
