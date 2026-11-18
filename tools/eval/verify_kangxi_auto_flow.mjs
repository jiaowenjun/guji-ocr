// Feasibility experiment only: compact semantic .gj -> explicit folded .gj.
// Does not change the production parser or annotations.
// node tools/eval/verify_kangxi_auto_flow.mjs [output-directory]
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import { compileAnnotation } from '../dataset/annotation_source.mjs';
import { exportLayout } from '../dataset/export_ocr_layout.mjs';
const { scanInline } = await import('../../guji-preview-grid/src/parser/inline-tokens.ts');
const { compileProfile } = await import('../../guji-preview-grid/src/ir/profile.ts');
const { GUJI_PROFILE } = await import('../../guji-preview-grid/src/ir/types.ts');
const { kangxiHeading } = await import('../../guji-preview-grid/src/semantics/kangxi.ts');
const { compileBookLayout } = await import('../../guji-preview-grid/src/ir/layout-config.ts');
const { layout3 } = await import('../../guji-preview-grid/src/ir/layout3.ts');

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const output = resolve(process.argv[2] ?? resolve(root, 'var/kangxi-auto-flow'));
mkdirSync(output, { recursive: true });
const config = JSON.parse(readFileSync(resolve(root, 'kangxi-gold/dataset-config.json'), 'utf8'));
const manifestRaw = readFileSync(resolve(root, 'kangxi-gold/manifest.json'), 'utf8');
const manifest = JSON.parse(manifestRaw);
const layout = compileBookLayout(config.layout.default.spec);
const clean = compileProfile(GUJI_PROFILE);
const sha = value => createHash('sha256').update(value).digest('hex');

// Remove all physical small-column/band breaks. Retain only page/size boundaries.
function compactSource(source) {
  const lines = [];
  let small = '';
  const flush = () => { if (small) lines.push(small); small = ''; };
  for (const raw of source.split('\n')) {
    const line = raw.replace(/　/g, '*').trim().replace(/[ \t]+/, ' ').split('//')[0];
    if (!line) continue;
    if (/^@\d+$/.test(line)) { flush(); lines.push(line, ''); continue; }
    const size = scanInline(line).tokens.find(token => token.kind === 'size');
    if (size) {
      small += line.slice(0, size.from); flush();
      lines.push(line.slice(size.from));
    } else small += line;
  }
  flush();
  return lines.join('\n') + '\n';
}

// Keep zero-width syntax attached while cutting at displayed cells, not UTF-16.
function units(raw) {
  const out = [];
  let prefix = '';
  for (const token of scanInline(raw).tokens) {
    const spelling = raw.slice(token.from, token.to);
    if (token.kind === 'size' || token.kind === 'comment') continue;
    const cells = clean(token.text).cells;
    if (cells.length) {
      if (token.size === 'small' && cells.length !== 1) throw Error('Unsupported small-cell normalization');
      out.push({ raw: prefix + spelling, text: cells.join('') }); prefix = '';
    } else if (token.kind === 'book-open' || prefix || !out.length) prefix += spelling;
    else out.at(-1).raw += spelling;
  }
  if (prefix && out.length) out.at(-1).raw += prefix;
  return out;
}

function fold(compact, specialCases) {
  const marker = /^@(\d+)$/m.exec(compact)?.[0];
  if (!marker) throw Error('Missing page marker');
  const bands = [];
  let lines = [], row = 0;
  const trace = [];
  const flush = () => {
    if (lines.length) bands.push(lines.join('\n'));
    lines = []; row = 0;
  };
  for (const line of compact.split('\n')) {
    if (!line || /^@\d+$/.test(line)) continue;
    const large = line.startsWith('#');
    const u = units(line);
    if (!u.length) continue;
    if (specialCases && large && kangxiHeading(line)) {
      flush(); lines.push(line); flush();
      trace.push({ kind: 'heading', band: bands.length, text: u.map(x => x.text).join('') });
      continue;
    }
    if (large) {
      for (const unit of u) {
        if (row + layout.largeRows > layout.rowCap) flush();
        trace.push({ kind: 'large', band: bands.length + 1, row: row + 1, text: unit.text });
        lines.push('#' + unit.raw); row += layout.largeRows;
      }
      continue;
    }
    // The standalone 古文 marker is centered, not an ordinary two-column gloss.
    // This recognition is a book-specific experimental rule, not generic .gj syntax.
    const centered = specialCases && ['古文', '古', '文'].includes(u.map(x => x.text).join(''));
    for (let i = 0; i < u.length;) {
      if (row === layout.rowCap) flush();
      const remaining = layout.rowCap - row;
      const count = Math.min(u.length - i, remaining * (centered ? 1 : 2));
      const first = centered ? count : Math.ceil(count / 2);
      const slice = u.slice(i, i + count);
      lines.push(slice.slice(0, first).map(x => x.raw).join(''));
      if (!centered && count > first) lines.push(slice.slice(first).map(x => x.raw).join(''));
      trace.push({ kind: centered ? 'centered' : 'small', band: bands.length + 1,
        row: row + 1, availableRows: remaining, groupCells: u.length, offset: i,
        count, lengths: centered ? [first] : [first, count - first],
        texts: [slice.slice(0, first).map(x => x.text).join(''),
          ...(!centered ? [slice.slice(first).map(x => x.text).join('')] : [])] });
      row += first; i += count;
    }
  }
  flush();
  return { source: marker + '\n\n' + bands.join('\n\n') + '\n', trace, bands: bands.length };
}

function canonical(exported) {
  return {
    text: exported.text, cols: exported.cols, rows: exported.rows,
    bands: exported.bands.map(b => ({ bbox: b.grid_bbox, empty: b.empty })),
    glyphs: exported.glyphs.map(g => ({ text: g.text, size: g.size_class,
      bbox: g.grid_bbox, ligature: g.ligature, circled: g.circled })),
    gaps: exported.gaps.map(g => g.grid_bbox),
    decorations: exported.decorations.map(d => ({ kind: d.kind, bbox: d.grid_bbox,
      openTop: d.open_top, openBottom: d.open_bottom })).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))),
  };
}

function compare(a, b) {
  const ca = canonical(a), cb = canonical(b);
  const differences = ca.glyphs.flatMap((g, i) => isDeepStrictEqual(g, cb.glyphs[i]) ? []
    : [{ index: i, standard: g, auto: cb.glyphs[i] }]);
  return { equal: isDeepStrictEqual(ca, cb),
    checks: Object.fromEntries(Object.keys(ca).map(key => [key, isDeepStrictEqual(ca[key], cb[key])])),
    firstGlyphMismatch: ca.glyphs.findIndex((g, i) => !isDeepStrictEqual(g, cb.glyphs[i])),
    differingGlyphs: differences.length, firstDifferences: differences.slice(0, 5),
    counts: { glyphs: ca.glyphs.length, gaps: ca.gaps.length,
      bookFragments: ca.decorations.filter(d => d.kind === 'book_title').length,
      circles: ca.decorations.filter(d => d.kind === 'circle').length },
  };
}

const results = [];
const inputs = new Map();
for (const entry of manifest.pages) {
  const path = resolve(root, 'kangxi-gold/annotations', entry.annotations.gj);
  const source = readFileSync(path, 'utf8'); inputs.set(path, source);
  const compact = compactSource(source);
  const baseline = exportLayout(source, entry.page, config);
  const row = { page: entry.page, status: entry.status, sourceSha256: sha(source), compactSha256: sha(compact) };
  for (const specialCases of [false, true]) {
    const mode = specialCases ? 'withTitleAndGuwen' : 'plain';
    const result = fold(compact, specialCases);
    try {
      const auto = exportLayout(result.source, entry.page, config);
      row[mode] = { ...compare(baseline, auto), bands: result.bands };
      if (specialCases && !row[mode].equal) {
        writeFileSync(resolve(output, `${entry.page}-compact.gj`), compact);
        writeFileSync(resolve(output, `${entry.page}-auto-folded.gj`), result.source);
      }
      if (entry.page === 382 && !specialCases) {
        for (const [name, value] of Object.entries({ 'standard.gj': source, 'compact.gj': compact,
          'auto-folded.gj': result.source, 'standard-layout.json': JSON.stringify(baseline),
          'auto-layout.json': JSON.stringify(auto), 'trace.json': JSON.stringify(result.trace, null, 2) }))
          writeFileSync(resolve(output, name), value + (name.endsWith('.json') ? '\n' : ''));
        row.trace = result.trace;
        const current = compileAnnotation(compact, entry.page, config);
        row.currentParserCompactDiagnostics = layout3(current.ir)[0].diagnostics;
      }
    } catch (error) { row[mode] = { equal: false, bands: result.bands, error: error.message }; }
  }
  // Scan-reviewed missing spaces, used in memory only. Never rewrite annotations.
  const repairs = entry.page === 339 ? [['叶下遷虔。【說文】', '叶下遷虔。*【說文】']]
    : entry.page === 353 ? [['一本作軋軋。【說文徐註】', '一本作軋軋。*【說文徐註】']] : [];
  if (repairs.length) {
    let candidate = source;
    const changes = [];
    for (const [from, to] of repairs) {
      if (candidate.split(to).length === 2 && !candidate.includes(from)) continue;
      if (candidate.split(from).length !== 2) throw Error(`Repair anchor mismatch: ${entry.page}`);
      candidate = candidate.replace(from, to);
      changes.push([from, to]);
    }
    const candidateFold = fold(compactSource(candidate), true);
    row.inMemorySpaceRepair = { changes, alreadyCorrected: changes.length === 0,
      ...compare(exportLayout(candidate, entry.page, config), exportLayout(candidateFold.source, entry.page, config)) };
    writeFileSync(resolve(output, `${entry.page}-space-repair-candidate.gj`), candidate);
  }
  results.push(row);
}
for (const [path, source] of inputs) {
  if (readFileSync(path, 'utf8') !== source) throw Error(`Source changed during audit: ${path}`);
}
if (readFileSync(resolve(root, 'kangxi-gold/manifest.json'), 'utf8') !== manifestRaw)
  throw Error('Manifest changed during audit');
const result = { schema: 'kangxi-auto-flow-feasibility/1', auditedAt: new Date().toISOString(),
  node: process.version, config: layout, manifestSha256: sha(manifestRaw), scriptSha256: sha(readFileSync(fileURLToPath(import.meta.url))),
  scope: 'Current sources; exact comparison of visible grid placement, blanks and decorations, ignoring generated identifiers and source offsets',
  summary: Object.fromEntries(['plain', 'withTitleAndGuwen'].map(mode => [mode, {
    equal: results.filter(r => r[mode].equal).length,
    different: results.filter(r => !r[mode].equal).map(r => r.page),
  }])), pages: results };
result.summary.withScanReviewedSpaceRepairs = {
  equal: results.filter(r => r.inMemorySpaceRepair?.equal ?? r.withTitleAndGuwen.equal).length,
  different: results.filter(r => !(r.inMemorySpaceRepair?.equal ?? r.withTitleAndGuwen.equal)).map(r => r.page),
  annotationsModified: false,
};
writeFileSync(resolve(output, 'audit.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify({ summary: result.summary, page382: results.find(r => r.page === 382) }, null, 2));
if (!results.find(r => r.page === 382)?.plain.equal) process.exitCode = 1;
