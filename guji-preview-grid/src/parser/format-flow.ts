import { gj2ir, gjSourceLines } from "../ir/gj2ir";
import { applyBookLayout } from "../ir/document-layout";
import type { BookLayout } from "../ir/layout-config";
import { KANGXI_DATASET } from "../datasets/kangxi";
import { scanInline } from "./inline-tokens";

/** Spell the materialized skeleton with its original punctuation, books and comments.
 * The formatter and renderer share flowDocument; no second wrapping algorithm. */
export function formatFlow(source: string, book: BookLayout = KANGXI_DATASET.layout): string {
  const hasPage = gjSourceLines(source).some(l => /^@\d+\s*(?:\/\/.*)?$/.test(l.text));
  const text = hasPage ? source : `@0\n${source}`;
  const doc = applyBookLayout(gj2ir(text), book);
  const spellings = new Map<number, string>();
  let prefix = "", last: number | undefined;
  const headers = new Map<number, string>();
  const emptyContent = new Map<number, string>();
  let currentPage: number | undefined;
  const append = (s: string) => {
    if (last === undefined) prefix += s;
    else spellings.set(last, spellings.get(last)! + s);
  };
  for (const line of gjSourceLines(text)) {
    const marker = /^@(\d+)\s*(?:\/\/.*)?$/.exec(line.text);
    if (marker) {
      if (currentPage !== undefined && prefix) { emptyContent.set(currentPage, prefix); prefix = ""; }
      headers.set(line.from, prefix + line.text); prefix = ""; last = undefined; currentPage = line.from; continue;
    }
    for (const t of scanInline(line.text).tokens) {
      if (t.kind === "size" || t.kind === "break") continue;
      if (t.kind === "comment") {
        const leading = line.text.slice(0, t.from);
        append(`${leading.trim() ? /[ \t]*$/.exec(leading)![0] : last === undefined ? "" : "\n"}${line.text.slice(t.from)}\n`);
        continue;
      }
      if (t.kind === "book-open") { prefix += "【"; continue; }
      if (t.kind === "book-close") { if (prefix) prefix += "】"; else append("】"); continue; }
      const pos = line.from + t.contentFrom;
      const raw = t.kind === "circle" ? `(${t.text.replace(/ /g, "*")})` : t.text === " " ? "*" : line.text.slice(t.from, t.to);
      spellings.set(pos, prefix + raw); prefix = ""; last = pos;
    }
  }
  if (last !== undefined) { const tail = prefix; prefix = ""; append(tail); }
  else if (currentPage !== undefined) { emptyContent.set(currentPage, prefix); prefix = ""; }
  const pages = doc.pages.map(page => {
    const bands = page.bands.map(band => {
      const lines = band.lines.map(line => {
        const large = line.elements[0]?.class === "large";
        const atoms: string[] = [];
        let previous: number | undefined;
        for (const pos of line.cpSrcs ?? []) {
          if (pos === previous) continue; // Multiple circle characters share one spelling.
          atoms.push(spellings.get(pos) ?? ""); previous = pos;
        }
        let value = atoms.join("");
        if (large) value = value.split("\n").map(s => s && !s.trimStart().startsWith("//") ? "#" + s : s).join("\n");
        // An internal literal $/¥ must not turn into a command after cosmetic
        // wrapping. A trailing empty # scope keeps that spelling non-terminal.
        return value.trimEnd().replace(/([$¥])$/u, "$1#");
      }).filter(Boolean);
      if (band.breakAfter && lines.length) {
        const end = lines.length - 1;
        // $ precedes an inline comment and is always the last non-comment token.
        const parts = lines[end].split("\n");
        const at = parts.findLastIndex(s => scanInline(s).tokens.some(t => t.kind === "text" || t.kind === "circle"));
        if (at >= 0) {
          const comment = parts[at].indexOf("//");
          parts[at] = comment < 0 ? parts[at] + "$" : parts[at].slice(0, comment).trimEnd() + "$ " + parts[at].slice(comment);
          lines[end] = parts.join("\n");
        }
      }
      return lines.join("\n");
    });
    const heading = hasPage ? headers.get(page.src![0]) ?? `@${page.no}` : "";
    return [heading, ...bands, emptyContent.get(page.src![0])].filter(Boolean).join("\n\n");
  });
  const result = (pages.join("\n\n") || prefix).trim();
  return result ? result + "\n" : "";
}
