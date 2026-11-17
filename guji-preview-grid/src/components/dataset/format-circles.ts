// Generic normalization; comments are preserved and headings need no special case.
export function formatCircles(text: string): { text: string; count: number } {
  let count = 0;
  const out = text
    .split("\n")
    .map((line) => {
      if (/^\s*\/\//.test(line)) return line; // 整行注释
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
