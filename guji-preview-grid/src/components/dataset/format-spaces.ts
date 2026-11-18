// Generic normalization; comments are preserved and headings need no special case.
export function formatSpaces(text: string): { text: string; count: number } {
  let count = 0;
  const out = text
    .split(/\r?\n/)
    .map((line) => {
      const stripped = line.replace(/[ \t]+$/, ""); // 只清除行尾半角空白；全角空格始终占格
      // 页码与注释中的空白不属于正文，保持原有的尾空白清理。
      if (/^[ \t]*\/\//.test(stripped) || /^[ \t]*@\d+\s*(?:\/\/.*)?$/.test(stripped)) {
        return stripped.replace(/[ \t　]+$/, "");
      }
      const ci = stripped.indexOf("//");
      const body = ci >= 0 ? stripped.slice(0, ci) : stripped;
      const forced = /[ \t]*([$¥])[ \t]*$/.exec(body);
      const head = forced ? body.slice(0, forced.index) : body;
      const tail = ci >= 0 ? stripped.slice(ci).replace(/[ \t　]+$/, "") : "";
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
