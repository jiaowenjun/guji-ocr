// Generic normalization; comments are preserved and headings need no special case.
export function formatSpaces(text: string): { text: string; count: number } {
  let count = 0;
  const out = text
    .split(/\r?\n/)
    .map((line) => {
      // 页码缩进不属于正文；正文行首半角空格逐个占格，Tab 不占格。
      if (/^[ \t]*@\d+\s*(?:\/\/.*)?$/.test(line)) {
        return line.replace(/[ \t　]+$/, "");
      }
      const stripped = line.replace(/^[ \t]+/, (leading) => leading.replace(/ /g, () => {
        count += 1;
        return "*";
      }).replace(/\t/g, "")).replace(/[ \t]+$/, "");
      const ci = stripped.indexOf("//");
      const body = ci >= 0 ? stripped.slice(0, ci) : stripped;
      const forced = /[ \t]*([$¥])[ \t]*$/.exec(body);
      const head = forced ? body.slice(0, forced.index) : body;
      const tail = ci >= 0 ? stripped.slice(ci).replace(/[ \t　]+$/, "") : "";
      const full = head.replace(/　/g, () => {
        count += 1;
        return "*";
      });
      // 行内半角串仍合并为一个占格。
      const half = full.replace(/([^ \t])[ \t]+(?=[^ \t])/g, (_m, lead: string) => {
        count += 1;
        return lead + "*";
      });
      return half + (forced ? forced[1] : "") + tail;
    })
    .join("\n");
  return { text: out, count };
}
