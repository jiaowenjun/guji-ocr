import { scanInline } from "./inline-tokens";

/** Keep a leading comma with the preceding large glyph, before its newline/comment. */
export function attachLeadingCommas(text: string): string {
  const lines = text.split("\n");
  for (let i = 1; i < lines.length; i++) {
    const match = /^([ \t]*)(，+)/.exec(lines[i]);
    if (!match) continue;
    const previous = lines[i - 1];
    const tokens = scanInline(previous).tokens;
    const glyph = tokens.filter((t) => t.kind === "circle" ||
      (t.kind === "text" && !/^[ \t]+$/.test(previous.slice(t.from, t.to)))).at(-1);
    if (glyph?.size !== "large" || !glyph.text.trim()) continue;
    const comment = tokens.find((t) => t.kind === "comment");
    const end = previous.slice(0, comment?.from ?? previous.length).replace(/[ \t]+$/, "").length;
    lines[i - 1] = previous.slice(0, end) + match[2] + previous.slice(end);
    lines[i] = match[1] + lines[i].slice(match[0].length);
    // A punctuation-only line must not turn into a new band separator.
    if (!lines[i].trim()) lines.splice(i--, 1);
  }
  return lines.join("\n");
}

/** Normalize circle spelling only; never infer type size from content or insert a newline. */
export function normalizeInput(text: string): string {
  return text.split("\n").map((line) => {
    let out = "", last = 0;
    for (const t of scanInline(line).tokens) if (t.kind === "circle") {
      out += line.slice(last, t.from) + `(${t.text.replace(/ /g, "*")})`;
      last = t.to;
    }
    return out + line.slice(last);
  }).join("\n");
}

/** Formatting preserves physical newlines: they terminate the # size scope. */
export function formatGj(text: string): string {
  const lines = attachLeadingCommas(normalizeInput(text)).split("\n").map((line) => {
    let seen = false, out = "", last = 0;
    for (const t of scanInline(line).tokens) if (t.kind === "size") {
      if (seen) { out += line.slice(last, t.from); last = t.to; }
      seen = true;
    }
    return out + line.slice(last);
  });
  const blankish = (s: string) => !s.trim() || s.trimStart().startsWith("//");
  while (lines.length && blankish(lines[0])) lines.shift();
  while (lines.length && blankish(lines.at(-1)!)) lines.pop();
  return lines.length ? lines.join("\n").replace(/[ \t]+$/, "") + "\n" : "";
}

/** Compatibility chunk view; parsing itself uses the canonical IR pipeline. */
export function split(text: string): string[] {
  return normalizeInput(text).replace(/[\s\S]*==.*/, "").split("\n")
    .map((l) => l.replace(/　/g, "*").trim().replace(/[ \t]+/, " "))
    .join("\n").split(/\n\s*\n/).map((s) => s.trim()
      .replace(/[。，·":：、《》]/g, "").replace(/\/\/[^\n]*/g, "").replace(/[◎〇]/g, "○"))
    .filter((s) => s.length > 0);
}
