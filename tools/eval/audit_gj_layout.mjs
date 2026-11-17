// Read-only corpus audit. Requires Node >= 22.18 with native TypeScript stripping.
// node tools/eval/audit_gj_layout.mjs [output.json] [--check] [--strict-layout] [--pages=312,313]
// --check checks source/derived files and skeleton independence; legacy parity is informational.
// --strict-layout additionally fails on geometry warnings; it does not certify scan fidelity.
import { registerHooks } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';

registerHooks({ resolve(specifier, context, nextResolve) {
  try { return nextResolve(specifier, context); }
  catch (error) {
    if (specifier.startsWith('.') && !/\.[a-z]+$/.test(specifier))
      return nextResolve(`${specifier}.ts`, context);
    throw error;
  }
} });
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const { gj2ir } = await import('../../guji-preview-grid/src/ir/gj2ir.ts');
const { layout3 } = await import('../../guji-preview-grid/src/ir/layout3.ts');
const { kangxiBandHeading } = await import('../../guji-preview-grid/src/semantics/kangxi.ts');
const { irToText } = await import('../../guji-preview-grid/src/ir/text.ts');
const { parsePages } = await import('../../guji-preview-grid/src/parser/parse-pages.ts');
const manifest = JSON.parse(readFileSync(resolve(root, 'kangxi-gold/manifest.json'), 'utf8'));
const pageArg = process.argv.find(arg => arg.startsWith('--pages='));
const selectedPages = pageArg ? pageArg.slice('--pages='.length).split(',').map(Number) : null;
if (selectedPages?.some(n => !Number.isInteger(n) || !manifest.pages.some(p => p.page === n)))
  throw Error('--pages must contain page numbers present in manifest.json');
const entries = manifest.pages.filter(p => !selectedPages || selectedPages.includes(p.page));
const cp = s => [...s].length;
const hist = values => values.reduce((out, n) => ((out[n] = (out[n] ?? 0) + 1), out), {});
const sha = s => createHash('sha256').update(s).digest('hex');
const rows = [];
const texts = [];
for (const entry of [...entries].sort((a, b) => a.page - b.page)) {
  const stem = String(entry.page).padStart(4, '0');
  const base = resolve(root, 'kangxi-gold/annotations', stem);
  const source = readFileSync(`${base}.gj`, 'utf8');
  const stored = JSON.parse(readFileSync(`${base}.json`, 'utf8'));
  const txt = readFileSync(`${base}.txt`, 'utf8');
  const doc = gj2ir(source);
  const page = doc.pages[0];
  if (doc.pages.length !== 1 || page.no !== entry.page) throw Error(`Invalid page ${stem}`);
  const laid = layout3(doc)[0];
  const bands = page.bands;
  const lines = bands.flatMap(b => b.lines);
  const elements = lines.flatMap(l => l.elements);
  const books = doc.overlays.filter(o => o.kind === 'book-title');
  const linePositions = new Map();
  const lineBands = new Map(bands.flatMap(b => b.lines.map(l => [l.id, b.id])));
  let offset = 0;
  for (const line of lines) {
    linePositions.set(line.id, offset);
    offset += cp(line.elements.map(e => e.text).join(''));
  }
  const intervals = books.map(o => ({ id: o.id, from: Math.min(...o.spans.map(s => linePositions.get(s.line) + s.range[0])), to: Math.max(...o.spans.map(s => linePositions.get(s.line) + s.range[1])) }));
  const crossings = [];
  for (let i = 0; i < intervals.length; i++) for (let j = i + 1; j < intervals.length; j++) {
    const [a, b] = [intervals[i], intervals[j]].sort((x, y) => x.from - y.from);
    if (a.from < b.from && b.from < a.to && a.to < b.to) crossings.push([a.id, b.id]);
  }
  const stripped = JSON.parse(JSON.stringify({ ...doc, overlays: [] }), (k, v) => k === 'src' || k === 'cpSrcs' ? undefined : v);
  const legacyText = parsePages(source).map(p => p.l.map(l => ('c' in l ? l.c : [l]).map(b => b.t ?? '').join('')).join('\n') + '\n').join('');
  const runs = laid.bands.flatMap(b => b.items.filter(i => i.kind === 'run'));
  const overflow = laid.bands.filter(b => b.rows > laid.config.rowCap).map(b => ({ id: b.id, rows: b.rows, cols: b.cols,
    hiddenSmallCells: b.items.filter(i => i.kind === 'run').reduce((n, i) => n + Math.max(0, i.cells.length - Math.max(0, laid.config.rowCap - i.r)), 0),
    clippedLarge: b.items.filter(i => i.kind === 'large' && i.r + laid.config.largeRows > laid.config.rowCap).map(i => ({ text: i.text, r: i.r })) }));
  let depth = 0, nestedOpeners = 0;
  for (const ch of source) {
    if (ch === '【') { if (depth > 0) nestedOpeners++; depth++; }
    if (ch === '】') depth = Math.max(0, depth - 1);
  }
  const activeLines = source.split(/\r?\n/).filter(l => l.trim() && !l.trim().startsWith('//'));
  rows.push({ page: entry.page, status: entry.status, sourceSha256: sha(source),
    jsonFresh: isDeepStrictEqual(doc, stored), txtFresh: irToText(doc) === txt,
    legacyTextEqual: irToText(doc) === legacyText, overlaySourceIndependent: isDeepStrictEqual(layout3(doc), layout3(stripped)),
    pageMarkers: activeLines.filter(l => /^@\d+$/.test(l.trim())).length,
    activeSourceLines: activeLines.length, headSourceLines: activeLines.filter(l => /^#[^#\s]/u.test(l)).length,
    startsWithSmallText: (!bands[0] || !kangxiBandHeading(bands[0], doc)) && bands[0]?.lines[0]?.elements[0]?.class === 'small',
    literalStars: (source.match(/\*/g) ?? []).length, openBrackets: (source.match(/【/g) ?? []).length, closeBrackets: (source.match(/】/g) ?? []).length,
    literalCircledIntroducers: (source.match(/#\(/g) ?? []).length, guwenOccurrences: (source.match(/古文/g) ?? []).length, guwenColonOccurrences: (source.match(/古文[:：]/g) ?? []).length,
    headings: bands.filter(b => kangxiBandHeading(b, doc)).length, bands: bands.length, lines: lines.length, elements: elements.length,
    largeElements: elements.filter(e => e.class === 'large').length, smallElements: elements.filter(e => e.class === 'small').length,
    largeCodepoints: elements.filter(e => e.class === 'large').reduce((n,e) => n + cp(e.text), 0),
    smallCodepoints: elements.filter(e => e.class === 'small').reduce((n,e) => n + cp(e.text), 0),
    ligatures: elements.filter(e => e.ligature).map(e => ({ id:e.id, text:e.text })),
    txtNonWhitespaceCodepoints: cp(txt.replace(/\s/g, '')),
    bookOverlays: books.length, bookSpans: books.reduce((n,o) => n + o.spans.length, 0),
    multiSpanBooks: books.filter(o => o.spans.length > 1).length,
    crossBandBooks: books.filter(o => new Set(o.spans.map(s => lineBands.get(s.line))).size > 1).length,
    openEndBooks: books.filter(o => o.closed === false).map(o => o.id),
    continuationBooks: books.filter(o => o.openedHere === false).map(o => o.id),
    circleOverlays: doc.overlays.filter(o => o.kind === 'circle').length,
    nestedOpeners, bookCrossings: crossings,
    rawLineLengths: lines.map(l => cp(l.elements.map(e => e.text).join(''))),
    runCellLengths: runs.map(i => i.cells.length),
    layoutDiagnostics: laid.diagnostics,
    layoutRows: laid.rows, totalCols: laid.totalCols, bandWidths: laid.bands.map(b => b.cols), bandHeights: laid.bands.map(b => b.rows),
    emptyBands: bands.filter(b => b.lines.every(l => l.elements.length === 0)).map(b => b.id), overflow });
  texts.push({ page: entry.page, source });
}
const totals = {};
for (const key of ['pageMarkers','activeSourceLines','headSourceLines','literalStars','openBrackets','closeBrackets','literalCircledIntroducers','guwenOccurrences','guwenColonOccurrences','headings','bands','lines','elements','largeElements','smallElements','largeCodepoints','smallCodepoints','txtNonWhitespaceCodepoints','bookOverlays','bookSpans','multiSpanBooks','crossBandBooks','circleOverlays','nestedOpeners']) totals[key] = rows.reduce((n,r) => n + r[key], 0);
const contiguous = [];
for (const t of texts) {
  let group = contiguous.at(-1);
  if (!group || group.at(-1).page + 1 !== t.page) contiguous.push(group = []);
  group.push(t);
}
const combined = contiguous.map(group => {
  const doc = gj2ir(group.map(t => t.source.trimEnd()).join('\n\n') + '\n');
  const linePage = new Map(doc.pages.flatMap(p => p.bands.flatMap(b => b.lines.map(l => [l.id, p.no]))));
  return { pages: group.map(t => t.page), bookOverlays: doc.overlays.filter(o => o.kind === 'book-title').length,
    crossPageBooks: doc.overlays.filter(o => o.kind === 'book-title' && new Set(o.spans.map(s => linePage.get(s.line))).size > 1).map(o => ({ pages: [...new Set(o.spans.map(s => linePage.get(s.line)))], spans: o.spans, closed: o.closed })) };
});
const rawLengths = rows.flatMap(r => r.rawLineLengths);
const runLengths = rows.flatMap(r => r.runCellLengths);
const probeBase = gj2ir('@1\n\n甲，乙\n\n丙丁\n');
const probeProfile = structuredClone(probeBase);
probeProfile.meta.profile.stripPunct = [];
const probeInserted = gj2ir('@1\n\n新\n\n甲，乙\n\n丙丁\n');
const summarizeBands = d => d.pages[0].bands.map(b => ({ id: b.id, text: b.lines.flatMap(l => l.elements.map(e => e.text)).join('') }));
const implementationFiles = [
  'guji-preview-grid/src/ir/types.ts', 'guji-preview-grid/src/ir/gj2ir.ts',
  'guji-preview-grid/src/ir/layout3.ts', 'guji-preview-grid/src/ir/text.ts',
  'guji-preview-grid/src/ir/profile.ts', 'guji-preview-grid/src/ir/layout-config.ts',
  'guji-preview-grid/src/ir/layout-diagnostics.ts', 'guji-preview-grid/src/ir/projection.ts',
  'guji-preview-grid/src/parser/structure.ts', 'guji-preview-grid/src/parser/inline-tokens.ts',
  'guji-preview-grid/src/semantics/kangxi.ts', 'guji-preview-grid/src/semantics/kangxi-rules.json',
  'guji-preview-grid/src/parser/split-line.ts', 'guji-preview-grid/src/parser/parse-pages.ts',
  'guji-preview-grid/src/parser/parse-line.ts', 'guji-preview-grid/src/parser/parse-inline.ts',
  'guji-preview-grid/src/components/matrix/MatrixPages.tsx',
];
const result = { schema: 'gj-layout-audit/2', auditedAt: new Date().toISOString(), node: process.version,
  scope: 'Current working tree; regenerated in memory; no annotation files written', selectedPages, pageCount: rows.length, statuses: hist(rows.map(r => r.status)), totals,
  implementationSha256: Object.fromEntries(implementationFiles.map(f => [f, sha(readFileSync(resolve(root, f)))])),
  manifestSha256: sha(readFileSync(resolve(root, 'kangxi-gold/manifest.json'))),
  checks: Object.fromEntries(['jsonFresh','txtFresh','legacyTextEqual','overlaySourceIndependent'].map(k => [k, { pass: rows.filter(r=>r[k]).length, failedPages: rows.filter(r=>!r[k]).map(r=>r.page) }])),
  distributions: { bandsPerPage: hist(rows.map(r=>r.bands)), smallTextAtPageStart: rows.filter(r=>r.startsWithSmallText).length,
    rawLineCodepoints: hist(rawLengths), rawLinesAbove24: rawLengths.filter(n=>n>24).length,
    renderedRunCellLengths: hist(runLengths), renderedRunsAbove24: runLengths.filter(n=>n>24).length,
    pageRows: hist(rows.map(r=>r.layoutRows)), pageCols: hist(rows.map(r=>r.totalCols)), bandWidths: hist(rows.flatMap(r=>r.bandWidths)), bandHeights: hist(rows.flatMap(r=>r.bandHeights)) },
  ligatureCount: rows.reduce((n,r)=>n+r.ligatures.length,0),
  openEndCount: rows.reduce((n,r)=>n+r.openEndBooks.length,0), continuationCount: rows.reduce((n,r)=>n+r.continuationBooks.length,0),
  crossingBookPairs: rows.reduce((n,r)=>n+r.bookCrossings.length,0),
  overflowingPages: rows.filter(r=>r.overflow.length).map(r=>({page:r.page,bands:r.overflow})),
  geometry: { warningPages: rows.filter(r => r.layoutDiagnostics.some(d => d.severity !== 'info')).map(r => r.page),
    diagnostics: rows.flatMap(r => r.layoutDiagnostics), imageReview: 'not performed by this audit' },
  probes: {
    profileInput: '@1\n\n甲，乙\n\n丙丁\n', profileChange: 'meta.profile.stripPunct = []',
    profileHonoredByLayout: !isDeepStrictEqual(layout3(probeBase), layout3(probeProfile)),
    profileHonoredByText: irToText(probeBase) !== irToText(probeProfile),
    positionalIdExample: { before: summarizeBands(probeBase), after: summarizeBands(probeInserted) },
  }, combined, pages: rows };
const output = process.argv.slice(2).find(arg => !arg.startsWith('--'));
if (output) writeFileSync(resolve(output), JSON.stringify(result, null, 2)+'\n');
if (process.argv.includes('--check') && ['jsonFresh', 'txtFresh', 'overlaySourceIndependent'].some(k => result.checks[k].failedPages.length)) process.exitCode = 1;
if (process.argv.includes('--strict-layout') && result.geometry.warningPages.length) process.exitCode = 1;
console.log(JSON.stringify({ ...result, pages: undefined, combined: combined.map(g=>({...g,crossPageBooks:g.crossPageBooks.map(o=>({pages:o.pages,closed:o.closed}))})) }, null, 2));
