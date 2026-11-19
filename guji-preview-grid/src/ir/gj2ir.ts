// .gj syntax -> semantic skeleton. Physical lines only terminate # and // scopes.
import type { IRBand, IRBookOverlay, IRDocument, IRElement, IRLine, IROverlay, IRPage } from "./types";
import { GUJI_PROFILE } from "./types";
import { scanInline } from "../parser/inline-tokens";

/** Shared source traversal: offsets are always original UTF-16 positions. */
export function gjSourceLines(text: string) {
  const lines: Array<{ text: string; from: number }> = [];
  const cut = /[\s\S]*==.*/.exec(text);
  let from = cut ? cut.index + cut[0].length + (text[cut.index + cut[0].length] === "\n" ? 1 : 0) : 0;
  for (const raw of text.slice(from).split("\n")) {
    // Leading spaces occupy cells, even on an otherwise blank line. Only page
    // marker indentation and whitespace after content are cosmetic.
    const line = raw.replace(/\r$/, "");
    const leading = /^[ \t]*/.exec(line)![0].length;
    const start = /^[ \t]*@\d+\s*(?:\/\/.*)?$/.test(line) ? leading : 0;
    const end = Math.max(leading, line.replace(/[ \t]+$/, "").length);
    lines.push({ text: line.slice(start, end), from: from + start });
    from += raw.length + 1;
  }
  return lines;
}

export function gj2ir(text: string): IRDocument {
  const pages: IRPage[] = [], overlays: IROverlay[] = [];
  let page: IRPage | undefined, band: IRBand | undefined;
  let book: IRBookOverlay | undefined;
  let serial = 0;
  let pendingBook: Array<{ line: string; range: [number, number] }> = [];
  let pendingFrom: number | undefined;
  const newBook = (from: number, openedHere: boolean) => {
    const overlay: IRBookOverlay = { id: `o${overlays.length}`, kind: "book-title", spans: [], src: [from, text.length], openedHere, closed: false };
    overlays.push(overlay);
    return overlay;
  };
  for (const source of gjSourceLines(text)) {
    const marker = /^@(\d+)\s*(?:\/\/.*)?$/.exec(source.text);
    if (marker) {
      page = { id: `p${marker[1].padStart(4, "0")}`, no: Number(marker[1]), src: [source.from, source.from + source.text.length], bands: [] };
      pages.push(page); band = undefined; pendingBook = []; pendingFrom = undefined; continue;
    }
    if (!page) continue;
    const tokens = scanInline(source.text, !!book).tokens;
    if (!tokens.some(t => t.kind === "text" || t.kind === "circle" || t.kind === "break" || t.kind === "book-open" || t.kind === "book-close")) continue;
    band ??= { id: `${page.id}-b${page.bands.length}`, ord: page.bands.length, lines: [] };
    if (!page.bands.includes(band)) page.bands.push(band);
    band.src ??= [source.from, source.from];
    band.src[1] = source.from + source.text.length;
    const line: IRLine = { id: `${band.id}-l${band.lines.length}`, ord: band.lines.length,
      src: [source.from, source.from + source.text.length], elements: [], cpSrcs: [] };
    let cp = 0;
    for (const token of tokens) {
      const pos = source.from + token.from;
      if (token.kind === "size") { pendingBook = []; pendingFrom = undefined; continue; }
      if (token.kind === "book-open") { book = newBook(pos, true); pendingBook = []; pendingFrom = undefined; continue; }
      if (token.kind === "book-close") {
        if (!book && pendingBook.length) { book = newBook(pendingFrom!, false); book.spans = pendingBook; }
        if (book) { book.closed = true; book.src![1] = source.from + token.to; book = undefined; }
        pendingBook = []; pendingFrom = undefined;
        continue;
      }
      if (token.kind === "break") { band.breakAfter = true; continue; }
      if (token.kind !== "text" && token.kind !== "circle") continue;
      const previous = line.elements.at(-1);
      let el: IRElement;
      if (token.size === "small" && previous?.class === "small") { el = previous; el.text += token.text; }
      else {
        el = { id: `e${serial++}`, class: token.size, text: token.text,
          ...(token.size === "large" && [...token.text].length > 1 ? { ligature: true } : {}) };
        line.elements.push(el);
      }
      const length = [...token.text].length;
      const spans = book ? book.spans : pendingBook;
      if (!book) pendingFrom ??= pos;
      const last = spans.at(-1);
      if (last?.line === line.id && last.range[1] === cp) last.range[1] += length;
      else spans.push({ line: line.id, range: [cp, cp + length] });
      if (token.kind === "circle") overlays.push({ id: `o${overlays.length}`, kind: "circle", target: el.id });
      for (const _ of token.text) line.cpSrcs!.push(source.from + token.contentFrom);
      cp += length;
    }
    if (line.elements.length) band.lines.push(line);
    if (band.breakAfter) band = undefined;
  }
  return { version: 3, meta: { sourceFormat: "gj/3", generatedBy: "guji-ir/3-auto", fidelity: "full",
    profile: structuredClone(GUJI_PROFILE), lineLayout: "auto", orientation: "vertical-rtl", rangeUnit: "codepoint", srcUnit: "utf-16" }, pages, overlays };
}
