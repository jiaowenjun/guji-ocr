// Generic normalization; comments are preserved and headings need no special case.
export function formatSpaces(text: string): { text: string; count: number } {
  let count = 0;
  const out = text
    .split("\n")
    .map((line) => {
      const stripped = line.replace(/[ \t　]+$/, ""); // 行尾空格（全角/半角/tab）清除，不再转 *
      if (/^\s*\/\//.test(stripped)) return stripped; // 整行注释
      const ci = stripped.indexOf("//");
      const body = ci >= 0 ? stripped.slice(0, ci) : stripped;
      const forced = /[ \t]*([$¥])[ \t]*$/.exec(body);
      const head = forced ? body.slice(0, forced.index) : body;
      const tail = ci >= 0 ? stripped.slice(ci) : "";
      const full = head.replace(/　/g, () => {
        count += 1;
        return "*";
      });
      // 行内半角串：两侧必须是非空格/tab 字符（行首/行尾的不动）
      const half = full.replace(/([^ \t])[ \t]+(?=[^ \t])/g, (_m, lead: string) => {
        count += 1;
        return lead + "*";
      });
      return half + (forced ? forced[1] : "") + tail;
    })
    .join("\n");
  return { text: out, count };
}
