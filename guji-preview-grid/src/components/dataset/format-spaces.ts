// Generic normalization; comments are preserved and headings need no special case.
export function formatSpaces(text: string): { text: string; count: number } {
  let count = 0;
  const out = text
    .split("\n")
    .map((line) => {
      if (/^\s*\/\//.test(line)) return line; // 整行注释
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
