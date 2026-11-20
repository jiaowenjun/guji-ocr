// <U+xxxx>（4–6 位十六进制）转写为实际字符；注释区不动，非法码位（超平面、代理区、控制符）保持原样。
export function formatCodepoints(text: string): { text: string; count: number } {
  let count = 0;
  const out = text
    .split("\n")
    .map((line) => {
      if (/^\s*\/\//.test(line)) return line; // 整行注释
      const ci = line.indexOf("//");
      const head = ci >= 0 ? line.slice(0, ci) : line;
      const tail = ci >= 0 ? line.slice(ci) : "";
      const next = head.replace(/<U\+([0-9A-Fa-f]{4,6})>/g, (m, hex: string) => {
        const cp = Number.parseInt(hex, 16);
        // 代理区/控制符会破坏行结构或无法渲染，超上限码位非法：均不转写。
        if (cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff) || cp < 0x20 || (cp >= 0x7f && cp <= 0x9f)) return m;
        count += 1;
        return String.fromCodePoint(cp);
      });
      return next + tail;
    })
    .join("\n");
  return { text: out, count };
}
