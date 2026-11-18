// Read-only audit of small-column groups in the current .gj sources.
// Node >= 22.18. Optional first argument: full JSON output path.
// This measures transcriptions; scan fidelity requires separate image review.
import { registerHooks } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

registerHooks({ resolve(specifier, context, nextResolve) {
  try { return nextResolve(specifier, context); }
  catch (error) {
    if (specifier.startsWith('.') && !/\.[a-z]+$/.test(specifier))
      return nextResolve(`${specifier}.ts`, context);
    throw error;
  }
} });

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const { parseKangxiDocument } = await import('../../guji-preview-grid/src/datasets/kangxi.ts');
const { planLayoutBand, layout3 } = await import('../../guji-preview-grid/src/ir/layout3.ts');
const sha = value => createHash('sha256').update(value).digest('hex');
const hist = values => values.reduce((out, value) => {
  out[value] = (out[value] ?? 0) + 1;
  return out;
}, {});
const balanced = (runs, key) => runs.length === 2
  && runs[0][key] - runs[1][key] >= 0 && runs[0][key] - runs[1][key] <= 1;
const manifestText = readFileSync(resolve(root, 'kangxi-gold/manifest.json'), 'utf8');
const manifest = JSON.parse(manifestText);
const pages = [];
const groups = [];

for (const entry of manifest.pages) {
  const file = `kangxi-gold/annotations/${entry.annotations.gj}`;
  const source = readFileSync(resolve(root, file), 'utf8');
  const doc = parseKangxiDocument(source);
  if (doc.pages.length !== 1 || doc.pages[0].no !== entry.page)
    throw new Error(`Page marker mismatch: ${file}`);
  const page = doc.pages[0];
  const laid = layout3(doc)[0];
  pages.push({ page: entry.page, status: entry.status, file, sha256: sha(source),
    bands: page.bands.length, diagnostics: laid.diagnostics });

  for (const [bandIndex, band] of page.bands.entries()) {
    const plan = planLayoutBand(band, doc.meta.profile);
    let row = 0;
    let groupIndex = 0;
    for (const [segmentIndex, segment] of plan.segments.entries()) {
      if (segment.kind === 'gap') { row += segment.rows; continue; }
      if (segment.kind === 'glyph') { row += laid.config.largeRows; continue; }
      const runs = segment.runs.map(run => {
        const line = band.lines.find(line => line.id === run.lineId);
        return { text: run.cells.join(''), cells: run.cells.length,
          characters: run.cells.filter(cell => !/\s/.test(cell)).length,
          sourceLine: source.slice(0, line.src[0]).split('\n').length,
          lineId: run.lineId };
      });
      const height = Math.max(...runs.map(run => run.cells));
      const previous = plan.segments[segmentIndex - 1];
      const next = plan.segments[segmentIndex + 1];
      groups.push({ id: `${entry.page}-${bandIndex + 1}-${++groupIndex}`,
        page: entry.page, status: entry.status, band: bandIndex + 1,
        startRow: row + 1, endRow: row + height,
        previous: previous?.kind === 'glyph' ? previous.text : null,
        next: next?.kind === 'glyph' ? next.text : null,
        runs, cellBalanced: balanced(runs, 'cells'), charBalanced: balanced(runs, 'characters') });
      row += height;
    }
  }
}

function summarize(selectedPages, selectedGroups) {
  const paired = selectedGroups.filter(group => group.runs.length === 2);
  return {
    pages: selectedPages.length, statuses: hist(selectedPages.map(page => page.status)),
    bands: selectedPages.reduce((sum, page) => sum + page.bands, 0),
    groups: selectedGroups.length, runsPerGroup: hist(selectedGroups.map(group => group.runs.length)),
    pairedCellDiff: hist(paired.map(group => group.runs[0].cells - group.runs[1].cells)),
    pairedCharDiff: hist(paired.map(group => group.runs[0].characters - group.runs[1].characters)),
    cellBalanced: paired.filter(group => group.cellBalanced).length,
    charBalanced: paired.filter(group => group.charBalanced).length,
    pairsWithExplicitSpaces: paired.filter(group => group.runs.some(run => run.cells !== run.characters)).length,
    pairsBeforeLargeGlyph: paired.filter(group => group.next !== null).length,
  };
}

const implementation = ['tools/eval/audit_small_column_balance.mjs',
  'kangxi-gold/dataset-config.json', 'guji-preview-grid/src/datasets/kangxi.ts',
  'guji-preview-grid/src/ir/gj2ir.ts', 'guji-preview-grid/src/ir/layout3.ts',
  'guji-preview-grid/src/ir/profile.ts', 'guji-preview-grid/src/ir/types.ts',
  'guji-preview-grid/src/parser/inline-tokens.ts'];
const result = {
  schema: 'kangxi-small-column-audit/1', auditedAt: new Date().toISOString(), node: process.version,
  scope: 'Current manifest and .gj; counts include only explicitly recorded blanks; no scan verification by this script',
  manifestSha256: sha(manifestText),
  implementationSha256: Object.fromEntries(implementation.map(file => [file, sha(readFileSync(resolve(root, file)))])),
  summary: summarize(pages, groups),
  firstSummary: summarize(pages.filter(page => page.status === 'first'), groups.filter(group => group.status === 'first')),
  pages, groups,
};
if (process.argv[2]) writeFileSync(resolve(process.argv[2]), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify({ summary: result.summary, firstSummary: result.firstSummary,
  pairedCellExceptions: groups.filter(group => group.runs.length === 2 && !group.cellBalanced),
  nonPairedGroups: groups.filter(group => group.runs.length !== 2).map(group => ({
    id: group.id, status: group.status, texts: group.runs.map(run => run.text),
  })),
}, null, 2));
