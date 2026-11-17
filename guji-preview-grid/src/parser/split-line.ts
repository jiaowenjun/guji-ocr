import { scanInline } from "./inline-tokens";
import { isBlankBand } from "./structure";

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
  const lines = normalizeInput(text).split("\n").map((line) => {
    if (isBlankBand(line)) return line.replace(/^[ \t]*#(?=[ \t]*(?:\/\/|$))/, "@blank");
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
