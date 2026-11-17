// Compatibility PageModel adapter over the canonical parser; no second grammar.
import { gj2ir } from "../ir/gj2ir";
import type { IRBand, IRDocument, IRProfile } from "../ir/types";
import { compileProfile } from "../ir/profile";
import type { BlockModel } from "../components/flex/model";
export type BookStyle = "book" | "book-start" | "book-middle" | "book-end";

export function bandToBlocks(band: IRBand, doc: IRDocument, profile?: IRProfile): BlockModel[] {
  const blocks: BlockModel[] = [];
  const clean = profile ? compileProfile(profile) : (s: string) => ({ cells: [...s] });
  const circles = new Set(doc.overlays.filter((o) => o.kind === "circle").map((o) => o.target));
  const books = doc.overlays.filter((o) => o.kind === "book-title");
  band.lines.forEach((line, li) => {
    if (li) blocks.push({ st: "br" });
    let cp = 0;
    for (const el of line.elements) {
      const chars = [...el.text];
      const groups = el.class === "large" ? [chars] : chars.map((c) => [c]);
      for (const chars of groups) {
        let st: string | undefined;
        for (const book of books) {
          const si = book.spans.findIndex((s) => s.line === line.id && cp >= s.range[0] && cp < s.range[1]);
          if (si < 0) continue;
          const open = si === 0 && book.openedHere !== false;
          const close = si === book.spans.length - 1 && book.closed !== false;
          st = open ? close ? "book" : "book-start" : close ? "book-end" : "book-middle";
          break;
        }
        if (circles.has(el.id)) st = "circle";
        const text = clean(chars.join("")).cells.join("");
        const si = el.class === "large" ? "large" : undefined;
        if (text) {
          const prev = blocks.at(-1);
          if (!si && prev?.t && prev.si === si && prev.st === st) prev.t += text;
          else blocks.push({ t: text, ...(si ? { si } : {}), ...(st ? { st } : {}) });
        }
        cp += chars.length;
      }
    }
  });
  return blocks;
}
export function parseInline(source: string): BlockModel[] {
  const doc = gj2ir(`@1\n\n${source}\n`);
  return doc.pages[0].bands.flatMap((b) => bandToBlocks(b, doc));
}
