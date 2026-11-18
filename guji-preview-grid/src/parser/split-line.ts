import { formatFlow } from "./format-flow";
import type { BookLayout } from "../ir/layout-config";
import { scanInline } from "./inline-tokens";

/** Keep a leading comma with the preceding large glyph, before its newline/comment. */
export function attachLeadingCommas(text: string): string {
  const lines = text.split("\n");
  for (let i = 1; i < lines.length; i++) {
    const match = /^([ \t]*)(，+)/.exec(lines[i]);
    if (!match) continue;
    let previousIndex = i - 1;
    while (previousIndex >= 0 && !lines[previousIndex].trim()) previousIndex--;
    if (previousIndex < 0) continue;
    const previous = lines[previousIndex];
    const tokens = scanInline(previous).tokens;
    const glyph = tokens.filter((t) => t.kind === "circle" ||
      (t.kind === "text" && !/^[ \t]+$/.test(previous.slice(t.from, t.to)))).at(-1);
    if (glyph?.size !== "large" || !glyph.text.trim()) continue;
    const comment = tokens.find((t) => t.kind === "comment" || t.kind === "break");
    const end = previous.slice(0, comment?.from ?? previous.length).replace(/[ \t]+$/, "").length;
    lines[previousIndex] = previous.slice(0, end) + match[2] + previous.slice(end);
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

/** Canonical folding is derived from the same automatic layout as preview. */
export function formatGj(text: string, book?: BookLayout): string {
  return formatFlow(attachLeadingCommas(normalizeInput(text)), book);
}

/** Compatibility chunk view; parsing itself uses the canonical IR pipeline. */
export function split(text: string): string[] {
  return normalizeInput(text).replace(/[\s\S]*==.*/, "").split("\n")
    .map((l) => l.replace(/　/g, "*").trim().replace(/[ \t]+/, " "))
    .join("\n").split(/\n\s*\n/).map((s) => s.trim()
      .replace(/[。，·":：、《》]/g, "").replace(/\/\/[^\n]*/g, "").replace(/[◎〇]/g, "○"))
    .filter((s) => s.length > 0);
}
