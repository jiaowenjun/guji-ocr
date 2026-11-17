// Canonical OCR geometry in grid units. Uses the production parser and layout.
// stdin: {manifest: absolutePath, pages: [312, ...]}; stdout: JSON array.
import { registerHooks } from 'node:module';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

registerHooks({ resolve(s, c, next) {
  try { return next(s, c); } catch (error) {
    if (s.startsWith('.') && !/\.[a-z]+$/.test(s)) return next(`${s}.ts`, c);
    throw error;
  }
} });
const { applyBookLayout } = await import('../../guji-preview-grid/src/ir/document-layout.ts');
const { resolveDatasetConfig, resolvePageScan } = await import('../../guji-preview-grid/src/datasets/config.ts');
const { resolveDatasetIndexConfig } = await import('../../guji-preview-grid/src/datasets/kangxi.ts');
const { gj2ir } = await import('../../guji-preview-grid/src/ir/gj2ir.ts');
const { layout3, planLayoutBand } = await import('../../guji-preview-grid/src/ir/layout3.ts');
const { getPageFrame } = await import('../../guji-preview-grid/src/ir/page-frame.ts');
const { projectBooks } = await import('../../guji-preview-grid/src/ir/projection.ts');
const { kangxiBandHeading } = await import('../../guji-preview-grid/src/semantics/kangxi.ts');
const { irToText } = await import('../../guji-preview-grid/src/ir/text.ts');
const compact = s => s.replace(/\s/gu, '');

export function exportLayout(source, pageNo, datasetConfig) {
  const dataset = resolveDatasetConfig(datasetConfig);
  const ir = applyBookLayout(gj2ir(source), dataset.layout);
  if (ir.pages.length !== 1 || ir.pages[0].no !== pageNo) throw Error(`Page marker mismatch: ${pageNo}`);
  const page = ir.pages[0], laid = layout3(ir)[0];
  const { cols, rows, colOffset } = getPageFrame(laid);
  const warnings = laid.diagnostics.filter(d => d.severity !== 'info');
  if (warnings.length) throw Error(`Layout ${pageNo}: ${warnings.map(d => d.message).join('; ')}`);
  const circles = new Map(ir.overlays.filter(o => o.kind === 'circle').map(o => [o.target, o.id]));
  const result = {
    page: pageNo, source, source_sha256: createHash('sha256').update(source).digest('hex'),
    ir, config: laid.config, scan: resolvePageScan(dataset, pageNo), cols, rows,
    transcription: irToText(ir), text: compact(irToText(ir)),
    bands: [], regions: [], glyphs: [], gaps: [], decorations: [],
  };
  let offset = 0;
  page.bands.forEach((band, bi) => {
    const placed = laid.bands[bi], left = laid.colStarts[bi] + colOffset;
    const meta = { id: band.id, order: bi, level: dataset.id === 'kangxi-gold' ? kangxiBandHeading(band, ir)?.level ?? null : null,
      grid_bbox: [left, 0, left + placed.cols, laid.config.rowCap], region_ids: [] };
    const plan = planLayoutBand(band, ir.meta.profile, laid.config);
    const elLine = new Map(band.lines.flatMap(l => l.elements.map(e => [e.id, l.id])));
    for (const seg of plan.segments) {
      const items = seg.kind === 'glyph'
        ? [placed.items.find(i => i.elId === seg.elId)]
        : seg.kind === 'parallel'
          ? seg.runs.map(r => placed.items.find(i => i.kind === 'run' && i.lineId === r.lineId && i.cpStart === r.cpStart))
          : [];
      for (const item of items) {
        if (!item) throw Error(`Missing placement in ${band.id}`);
        const large = item.kind === 'large';
        const x = left + item.c + (item.halfShift ?? 0), y = item.r;
        const width = large ? laid.config.largeCols : 1;
        const height = large ? laid.config.largeRows : item.cells.length;
        const id = large ? item.elId : `${item.lineId}-run-${item.cpStart}`;
        const region = { id, band_id: band.id, kind: large ? 'large' : 'text_run',
          size_class: large ? 'large' : 'small', line_id: large ? elLine.get(item.elId) : item.lineId,
          grid_bbox: [x, y, x + width, y + height], order: result.regions.length,
          text: compact(large ? item.text : item.cells.join('')),
          ligature: Boolean(item.ligature), circle_id: circles.get(item.elId) ?? null,
          glyph_ids: [], text_range: [offset, offset] };
        const cells = large ? [item.text] : item.cells;
        cells.forEach((text, i) => {
          const box = [x, y + (large ? 0 : i), x + width, y + (large ? height : i + 1)];
          const gid = `${id}-g${i}`;
          if (!compact(text)) {
            result.gaps.push({ id: gid, band_id: band.id, grid_bbox: box });
            return;
          }
          const glyph = { id: gid, region_id: id, band_id: band.id, text: compact(text),
            size_class: region.size_class, grid_bbox: box, order: result.glyphs.length,
            ligature: region.ligature, circled: Boolean(region.circle_id),
            text_range: [offset, offset + [...compact(text)].length],
            source: { line_id: region.line_id, element_id: large ? item.elId : null,
              raw_range: large ? null : item.rawRanges[i] } };
          offset = glyph.text_range[1];
          result.glyphs.push(glyph); region.glyph_ids.push(gid);
        });
        region.text_range[1] = offset;
        if (region.text) { result.regions.push(region); meta.region_ids.push(id); }
        if (region.circle_id) result.decorations.push({ id: region.circle_id,
          kind: 'circle', target: id, band_id: band.id, grid_bbox: region.grid_bbox });
      }
    }
    meta.empty = meta.region_ids.length === 0;
    result.bands.push(meta);
  });
  const books = projectBooks([laid], ir.overlays).get(laid);
  books.forEach((b, i) => result.decorations.push({
    id: `${b.overlayId}-fragment-${i}`, overlay_id: b.overlayId, kind: 'book_title',
    band_id: laid.bands[b.bandIdx].id,
    grid_bbox: [b.col + colOffset + (b.halfShift ?? 0), b.rowStart, b.col + colOffset + (b.halfShift ?? 0) + (b.cols ?? 1), b.rowEnd],
    open_top: b.openTop, open_bottom: b.openBottom,
  }));
  if (result.glyphs.map(g => g.text).join('') !== result.text ||
      result.regions.map(r => r.text).join('') !== result.text)
    throw Error(`Reading order mismatch: ${pageNo}`);
  return result;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const request = JSON.parse(readFileSync(0, 'utf8'));
  const manifest = JSON.parse(readFileSync(request.manifest, 'utf8'));
  const root = dirname(request.manifest);
  const configPath = resolve(root, 'dataset-config.json');
  const dataset = resolveDatasetIndexConfig(existsSync(configPath)
    ? JSON.parse(readFileSync(configPath, 'utf8')) : undefined, manifest.dataset);
  const records = request.pages.map(no => {
    const entry = manifest.pages.find(p => p.page === no);
    if (!entry) throw Error(`Page not in manifest: ${no}`);
    const file = resolve(root, 'annotations', entry.annotations.gj);
    return exportLayout(readFileSync(file, 'utf8'), no, dataset);
  });
  process.stdout.write(JSON.stringify(records));
}
