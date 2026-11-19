/** Generic .gj lexer. # selects large type until the physical newline; words never change size. */
export interface InlineToken {
  kind: "size" | "text" | "circle" | "book-open" | "book-close" | "break" | "comment";
  from: number;
  to: number;
  text: string;
  size: "small" | "large";
  book: boolean;
  contentFrom: number;
}

const CN = [..."零一二三四五六七八九"];
export function normalizeCircle(inner: string): string {
  return inner.replace(/z/gi, "增").replace(/\d+/g, (raw) => {
    const n = Number(raw);
    if (n > 99) return raw;
    if (n < 10) return CN[n];
    return (n < 20 ? "" : CN[Math.floor(n / 10)]) + "十" + (n % 10 ? CN[n % 10] : "");
  });
}

export function scanInline(line: string, inBook = false): { tokens: InlineToken[]; inBookAfter: boolean } {
  const tokens: InlineToken[] = [];
  let size: InlineToken["size"] = "small";
  let book = inBook;
  const leading = /^[ \t]*/.exec(line)![0].length;
  // An orphan closing bracket is a continuation even when the caller has no preceding page.
  const orphan = /^[^【#]*】/.exec(line)?.[0].length ?? 0;
  for (let i = 0; i < line.length;) {
    const from = i;
    const ch = String.fromCodePoint(line.codePointAt(i)!);
    const push = (kind: InlineToken["kind"], text: string, to: number, contentFrom = from) => {
      tokens.push({ kind, from, to, text, size, book: book || from < orphan, contentFrom });
      i = to;
    };
    if (line.startsWith("//", i)) { push("comment", "", line.length); break; }
    if ((ch === "$" || ch === "¥") && /^[ \t\r]*(?:\/\/.*)?$/.test(line.slice(i + 1))) { push("break", "", i + 1); continue; }
    if (i < leading) {
      if (ch === " ") push("text", " ", i + 1);
      else i++; // Leading tabs remain cosmetic; spaces keep individual source positions.
      continue;
    }
    if (ch === " " || ch === "\t") {
      const whitespace = /^[ \t]+/.exec(line.slice(i))![0];
      const rest = line.slice(i + whitespace.length);
      if (!rest || /^(?:\/\/|[$¥][ \t]*(?:\/\/|$))/.test(rest)) { i += whitespace.length; continue; }
      push("text", " ", i + whitespace.length); continue;
    }
    if (ch === "#") { size = "large"; push("size", "", i + 1); continue; }
    if (ch === "【") { book = true; push("book-open", "", i + 1); continue; }
    if (ch === "】") { push("book-close", "", i + 1); book = false; continue; }
    if (size === "large" && (ch === "(" || ch === "（")) {
      const rest = line.slice(i + 1);
      const closed = /^([^()（）#【】$¥\n]{1,2})[)）]/u.exec(rest);
      const inner = closed?.[1] ?? (/^[^()（）#【】$¥\n]/u.exec(rest)?.[0] ?? "");
      if (inner) {
        push("circle", normalizeCircle(inner.replace(/[*　]/g, " ")), i + 1 + (closed?.[0].length ?? inner.length), i + 1);
        continue;
      }
    }
    push("text", ch === "*" || ch === "　" ? " " : ch, i + ch.length);
  }
  return { tokens, inBookAfter: book };
}
