import type { IRBand, IRDocument, IRElement, IRLine } from "./types";
import { compileProfile } from "./profile";
import { resolveLayoutConfig } from "./layout-config";

type Point = { ch: string; line: string; cp: number; src?: number };
type Atom = { el: IRElement; points: Point[] };

/** Materialize automatic columns. Geometry uses only skeleton text, never overlays/source.
 * Reapplying a book preset joins automatic boundaries but preserves explicit $ boundaries. */
export function flowDocument(doc: IRDocument): IRDocument {
  if (doc.meta.lineLayout !== "auto") return doc;
  const clean = compileProfile(doc.meta.profile);
  const destinations = new Map<string, { line: string; cp: number }>();
  const elementIds = new Map<string, string>();
  const key = (line: string, cp: number) => `${line}:${cp}`;
  const pages = doc.pages.map(page => {
    const config = resolveLayoutConfig(page.layout ?? doc.meta.layout);
    const centeredGuwen = (page.layoutPreset ?? doc.meta.layoutPreset)?.id === "kangxi-wuyingdian";
    const bands: IRBand[] = [];
    let band: IRBand | undefined, row = 0, small: Point[] = [], largeLine: IRLine | undefined;
    let largeSourceLine: string | undefined;
    const getBand = () => band ??= { id: `${page.id}-b${bands.length}`, ord: bands.length, lines: [] };
    const flushBand = (forced = false) => {
      if (band?.lines.length) {
        if (forced) band.breakAfter = true;
        bands.push(band);
      } else if (forced && bands.length) bands[bands.length - 1].breakAfter = true;
      band = undefined; row = 0; largeLine = undefined;
    };
    const newLine = () => {
      const b = getBand();
      const l: IRLine = { id: `${b.id}-l${b.lines.length}`, ord: b.lines.length, elements: [] };
      b.lines.push(l); return l;
    };
    const append = (line: IRLine, points: Point[], el: IRElement) => {
      const cp = line.elements.reduce((n, e) => n + [...e.text].length, 0);
      const id = `${line.id}-e${line.elements.length}`;
      line.elements.push({ ...el, id });
      if (el.class === "large") elementIds.set(el.id, id);
      points.forEach((p, i) => destinations.set(key(p.line, p.cp), { line: line.id, cp: cp + i }));
      if (points.every(p => p.src !== undefined)) {
        (line.cpSrcs ??= []).push(...points.map(p => p.src!));
        const first = points[0], last = points.at(-1);
        if (first && last) {
          line.src = [line.src?.[0] ?? first.src!, last.src! + last.ch.length];
          const b = getBand(); b.src = [b.src?.[0] ?? line.src[0], line.src[1]];
        }
      }
    };
    const flushSmall = () => {
      if (!small.length) return;
      largeLine = undefined;
      const text = small.map(p => p.ch).join("");
      const { cells, ranges } = clean(text);
      // 古文 is a dictionary marker, laid out as a centered single small column.
      const centered = centeredGuwen && ["古文", "古", "文"].includes(cells.join(""));
      const width = centered ? 1 : config.smallColumnsPerBand;
      if (!cells.length) {
        append(newLine(), small, { id: "", class: "small", text });
        small = []; return;
      }
      let offset = 0, rawStart = 0;
      while (offset < cells.length) {
        if (row >= config.rowCap) flushBand();
        const count = Math.min(cells.length - offset, (config.rowCap - row) * width);
        const height = Math.ceil(count / width);
        let used = 0;
        for (let col = 0; col < width; col++) {
          const length = Math.floor(count / width) + (col < count % width ? 1 : 0);
          if (!length) { newLine().emptyRun = true; continue; }
          const end = offset + used + length;
          // Closing marks and sentence punctuation follow the preceding cell;
          // stripped opening book marks belong to the following cell instead.
          let rawEnd = end === cells.length ? small.length : ranges[end][0];
          if (end < cells.length) {
            while (rawEnd > ranges[end - 1][1] && small[rawEnd - 1].ch === "《") rawEnd--;
          }
          const points = small.slice(rawStart, rawEnd);
          if (points.length) append(newLine(), points, { id: "", class: "small", text: points.map(p => p.ch).join("") });
          rawStart = rawEnd; used += length;
        }
        offset += count; row += height;
      }
      small = [];
    };
    const addLarge = ({ el, points }: Atom) => {
      flushSmall();
      const height = clean(el.text).cells.length ? config.largeRows : 0;
      if (height && row + height > config.rowCap) flushBand();
      // Keep distinct # source scopes for dictionary headword navigation. This
      // changes no geometry: adjacent large lines still form one vertical stack.
      if (largeSourceLine !== points[0]?.line) largeLine = undefined;
      largeSourceLine = points[0]?.line;
      largeLine ??= newLine();
      append(largeLine, points, el); row += height;
    };
    for (const oldBand of page.bands) {
      for (const line of oldBand.lines) {
        let cp = 0;
        for (const el of line.elements) {
          const points = [...el.text].map(ch => { const i = cp++; return { ch, line: line.id, cp: i, src: line.cpSrcs?.[i] }; });
          if (el.class === "large") addLarge({ el, points });
          else small.push(...points);
        }
      }
      if (oldBand.breakAfter) { flushSmall(); flushBand(true); }
    }
    flushSmall(); flushBand();
    return { ...page, bands };
  });
  const overlays = (doc.overlays ?? []).map(overlay => {
    if (overlay.kind === "circle") return { ...overlay, target: elementIds.get(overlay.target) ?? overlay.target };
    const spans: typeof overlay.spans = [];
    for (const old of overlay.spans) for (let cp = old.range[0]; cp < old.range[1]; cp++) {
      const dest = destinations.get(key(old.line, cp));
      if (!dest) continue;
      const last = spans.at(-1);
      if (last?.line === dest.line && last.range[1] === dest.cp) last.range[1]++;
      else spans.push({ line: dest.line, range: [dest.cp, dest.cp + 1] });
    }
    return { ...overlay, spans };
  });
  return { ...doc, pages, overlays };
}
