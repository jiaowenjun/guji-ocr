/** Kangxi dictionary interpretation. No rule here changes glyph size or layout. */
import rules from "./kangxi-rules.json" with { type: "json" };
import { scanInline, type InlineToken } from "../parser/inline-tokens";
import type { IRBand, IRDocument } from "../ir/types";

export interface KangxiHeading { kind: "book" | "collection" | "radical"; text: string; level: 1 | 2 | 3 }
const content = (s: string) => [...s].filter((ch) => !rules.ignored.includes(ch) && !/\s/u.test(ch)).join("");
type Glyph = { text: string; size: string; circled?: boolean; book?: boolean };
function headingGlyphs(glyphs: Glyph[]): KangxiHeading | null {
  if (!glyphs.length || glyphs.some((g) => g.size !== "large" || g.circled || g.book)) return null;
  const text = glyphs.map((g) => g.text).join("");
  const indent = /^ */.exec(text)![0].length;
  const name = text.slice(indent);
  if (indent === 0 && name === rules.bookTitle) return { kind: "book", text: name, level: 1 };
  const chars = [...name];
  if (indent === 1 && chars.length === 3 && rules.collections.includes(chars[0]) && chars[1] === "集" && rules.parts.includes(chars[2]))
    return { kind: "collection", text: name, level: 2 };
  if (indent === 2 && chars.length === 2 && rules.radicals.includes(chars[0]) && chars[1] === "部")
    return { kind: "radical", text: name, level: 3 };
  return null;
}
export function kangxiHeading(line: string): KangxiHeading | null {
  const tokens = scanInline(line.replace(/^[ \t]+|[ \t]+$/g, "")).tokens;
  return headingGlyphs(tokens.filter((t) => t.kind === "text" || t.kind === "circle")
    .map((t) => ({ text: t.text, size: t.size, circled: t.kind === "circle", book: t.book })));
}
export function kangxiBandHeading(band: IRBand, doc: IRDocument): KangxiHeading | null {
  if (band.lines.length !== 1) return null;
  if (doc.overlays.some((o) => o.kind === "book-title" && o.spans.some((s) => s.line === band.lines[0].id))) return null;
  const circles = new Set(doc.overlays.filter((o) => o.kind === "circle").map((o) => o.target));
  return headingGlyphs(band.lines[0].elements.map((e) => ({ text: e.text, size: e.class, circled: circles.has(e.id) })));
}

export interface KangxiEntry {
  raw: string;
  chars: string[];
  /** Last main glyph is the lookup host; following guwen glyphs are variants. */
  head: string;
  line: number;
  start: number;
  endLine: number;
}

/** Cross-line guwen grouping belongs to the dictionary, never to the lexer. */
export function kangxiEntries(gj: string): KangxiEntry[] {
  const lines = gj.split("\n");
  const out: KangxiEntry[] = [];
  let current: KangxiEntry | undefined;
  let marker = "";
  let variants = false;
  let prefixLine: number | undefined;
  const small = (text: string) => {
    const s = content(text);
    if (!s) return;
    if (s === "古文" || (marker === "古" && s === "文")) { marker = "古文"; variants = true; }
    else if (s === "古") { marker = s; variants = false; }
    else { marker = ""; variants = false; prefixLine = undefined; }
  };
  for (const [li, raw] of lines.entries()) {
    const line = raw.trim();
    if (!line || line.startsWith("//") || line === "@blank" || line === "#") continue;
    if (/^@\d+$|^=+$/.test(line) || kangxiHeading(raw)) {
      current = undefined; marker = ""; variants = false; prefixLine = undefined; continue;
    }
    const tokens = scanInline(raw).tokens;
    const sizeAt = tokens.find((t) => t.kind === "size")?.from;
    if (sizeAt === undefined) { small(tokens.filter((t) => t.kind === "text").map((t) => t.text).join("")); continue; }
    small(tokens.filter((t) => t.kind === "text" && t.size === "small").map((t) => t.text).join(""));
    const glyphs = tokens.filter((t: InlineToken) => t.kind === "text" && t.size === "large" && !t.book)
      .flatMap((t) => [...content(t.text)]).filter((ch) => /[\p{Script=Han}\uE000-\uF8FF]/u.test(ch));
    if (!glyphs.length) {
      if (tokens.some((t) => t.kind === "circle")) prefixLine ??= li;
      continue;
    }
    if (variants && current) {
      current.chars.push(...glyphs); current.endLine = li;
      current.raw = lines.slice(current.line, li + 1).join("\n").slice(current.start);
    } else {
      const first = prefixLine ?? li;
      current = { raw: lines.slice(first, li + 1).join("\n").slice(first === li ? sizeAt : 0),
        chars: glyphs, head: glyphs.at(-1)!, line: first, start: first === li ? sizeAt : 0, endLine: li };
      out.push(current);
    }
    prefixLine = undefined;
  }
  return out;
}
