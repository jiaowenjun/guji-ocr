// IR skeleton → explicit vertical stacks/parallel runs → cell placements.
// Neither planning nor placement depends on overlays or source offsets.
import type { IRBand, IRDocument, IRProfile } from "./types";
import { compileProfile } from "./profile";
import { resolveLayoutConfig, type IRLayoutConfig } from "./layout-config";
import { diagnoseLayout, type LayoutDiagnostic } from "./layout-diagnostics";

interface L3Placement {
  r: number;
  c: number;
  lineId: string;
  cpStart: number;
}

export interface L3LargeItem extends L3Placement {
  kind: "large";
  text: string;
  ligature?: boolean;
  elId: string;
  cpEnd: number;
}

export interface L3RunItem extends L3Placement {
  kind: "run";
  cells: string[];
  /** 每个显示字格对应的行内原始码点区间；保留清洗的展开／收缩映射。 */
  rawRanges: Array<[number, number]>;
  halfShift?: 0.5;
}

export type L3Item = L3LargeItem | L3RunItem;

export interface L3Band {
  id: string;
  /** Explicit membership, including empty/stripped lines; IDs are opaque. */
  lineIds: string[];
  cols: number;
  rows: number;
  items: L3Item[];
}

export interface L3Page {
  no: number;
  rows: number;
  totalCols: number;
  bands: L3Band[];
  /** CSS grid columns run left → right; band 0 is the rightmost band. */
  colStarts: number[];
  config: IRLayoutConfig;
  diagnostics: LayoutDiagnostic[];
}

interface PlannedRun {
  lineId: string;
  cpStart: number;
  cells: string[];
  ranges: Array<[number, number]>;
}

export type LayoutSegment =
  | { kind: "glyph"; text: string; elId: string; ligature?: boolean; lineId: string; cpStart: number; cpEnd: number }
  | { kind: "parallel"; runs: PlannedRun[] }
  | { kind: "gap"; rows: number };

/** Rebuildable layout plan; it is not part of persisted IR. */
export interface BandPlan {
  id: string;
  lineIds: string[];
  segments: LayoutSegment[];
}

function planBand(band: IRBand, clean: ReturnType<typeof compileProfile>): BandPlan {
  const segments: LayoutSegment[] = [];
  const lineIds = band.lines.map((line) => line.id);
  let fragment: PlannedRun | null = null;
  let runs: PlannedRun[] = [];
  const flushFragment = () => {
    if (fragment?.cells.length) runs.push(fragment);
    fragment = null;
  };
  const flushGroup = () => {
    flushFragment();
    if (runs.length) segments.push({ kind: "parallel", runs });
    runs = [];
  };
  for (const line of band.lines) {
    if (line.emptyRun) runs.push({ lineId: line.id, cpStart: 0, cells: [], ranges: [] });
    let cp = 0;
    for (const el of line.elements) {
      const { cells, ranges } = clean(el.text);
      if (el.class === "small") {
        fragment ??= { lineId: line.id, cpStart: cp, cells: [], ranges: [] };
        fragment.cells.push(...cells);
        fragment.ranges.push(...ranges.map(([a, b]): [number, number] => [a + cp, b + cp]));
      } else {
        flushGroup();
        // Stripped punctuation occupies no slot. Explicit blanks remain real large cells.
        if (cells.length) segments.push({ kind: "glyph", text: cells.join(""), elId: el.id, ligature: el.ligature, lineId: line.id, cpStart: cp, cpEnd: cp + [...el.text].length });
      }
      cp += [...el.text].length;
    }
    flushFragment();
  }
  flushGroup();
  if (!segments.length) segments.push({ kind: "gap", rows: 0 });
  return { id: band.id, lineIds, segments };
}

export function planLayoutBand(band: IRBand, profile: IRProfile, config?: IRLayoutConfig): BandPlan {
  if (config !== undefined) resolveLayoutConfig(config);
  return planBand(band, compileProfile(profile));
}

function placeBand(plan: BandPlan, config: IRLayoutConfig): L3Band {
  const cols = Math.max(config.smallColumnsPerBand,
    ...plan.segments.map((s) => s.kind === "parallel" ? s.runs.length : s.kind === "glyph" ? config.largeCols : 0));
  // Preserve the established item order (large glyphs, then small runs).
  const glyphs: L3LargeItem[] = [];
  const small: L3RunItem[] = [];
  let r = 0;
  for (const segment of plan.segments) {
    if (segment.kind === "gap") r += segment.rows;
    else if (segment.kind === "glyph") {
      glyphs.push({ kind: "large", r, c: 0, text: segment.text, elId: segment.elId, ligature: segment.ligature, lineId: segment.lineId, cpStart: segment.cpStart, cpEnd: segment.cpEnd });
      r += config.largeRows;
    } else {
      const slack = cols - segment.runs.length;
      segment.runs.forEach((run, j) => small.push({
        kind: "run", r, c: Math.floor(slack / 2) + segment.runs.length - 1 - j,
        cells: run.cells, rawRanges: run.ranges,
        lineId: run.lineId, cpStart: run.cpStart, halfShift: slack % 2 ? 0.5 : undefined,
      }));
      r += Math.max(...segment.runs.map((run) => run.cells.length));
    }
  }
  return { id: plan.id, lineIds: plan.lineIds, cols, rows: r, items: [...glyphs, ...small] };
}

export function layout3(doc: IRDocument): L3Page[] {
  const clean = compileProfile(doc.meta.profile);
  return doc.pages.map((page) => {
    const config = resolveLayoutConfig(page.layout === undefined ? doc.meta.layout : page.layout);
    const bands = page.bands.map((band) => placeBand(planBand(band, clean), config));
    const rows = Math.max(config.largeRows, ...bands.map((b) => b.rows));
    const colStarts: number[] = [];
    let acc = 0;
    for (let i = bands.length - 1; i >= 0; i--) {
      colStarts[i] = acc;
      acc += bands[i].cols;
    }
    const laid: L3Page = { no: page.no, rows, totalCols: Math.max(config.smallColumnsPerBand, acc), bands, colStarts, config, diagnostics: [] };
    laid.diagnostics = diagnoseLayout(laid);
    return laid;
  });
}
