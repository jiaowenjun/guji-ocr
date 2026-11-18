// Shared .gj -> IR -> reading text pipeline. No writes during queries/evaluation.
import { registerHooks } from 'node:module';
import { readFileSync } from 'node:fs';
import { dirname, resolve, relative, isAbsolute } from 'node:path';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

registerHooks({ resolve(s, c, next) {
  try { return next(s, c); } catch (error) {
    if (s.startsWith('.') && !/\.[a-z]+$/.test(s)) return next(`${s}.ts`, c);
    throw error;
  }
} });
const { applyBookLayout } = await import('../../guji-preview-grid/src/ir/document-layout.ts');
const { resolveDatasetConfig } = await import('../../guji-preview-grid/src/datasets/config.ts');
const { resolveDatasetIndexConfig } = await import('../../guji-preview-grid/src/datasets/kangxi.ts');
const { gj2ir } = await import('../../guji-preview-grid/src/ir/gj2ir.ts');
const { irToText } = await import('../../guji-preview-grid/src/ir/text.ts');

export function compileAnnotation(source, page, config) {
  const ir = applyBookLayout(gj2ir(source), resolveDatasetConfig(config).layout);
  if (ir.pages.length !== 1 || ir.pages[0].no !== page) throw Error(`Page marker mismatch: ${page}`);
  return { ir, text: irToText(ir), source_sha256: createHash('sha256').update(source).digest('hex') };
}

export function readAnnotations(manifestPath, requestedPages) {
  const inputs = new Map();
  const read = file => {
    const text = readFileSync(file, 'utf8');
    inputs.set(file, text);
    return text;
  };
  const manifest = JSON.parse(read(manifestPath));
  const root = dirname(manifestPath);
  const config = resolveDatasetIndexConfig(JSON.parse(read(resolve(root, 'dataset-config.json'))), manifest.dataset);
  const entries = new Map();
  for (const entry of manifest.pages) {
    if (entries.has(entry.page)) throw Error(`Duplicate page: ${entry.page}`);
    entries.set(entry.page, entry);
  }
  const records = (requestedPages ?? [...entries.keys()]).map(page => {
    const entry = entries.get(page);
    if (!entry?.annotations?.gj) throw Error(`Missing .gj source in manifest: ${page}`);
    const dir = resolve(root, 'annotations');
    const file = resolve(dir, entry.annotations.gj);
    const rel = relative(dir, file);
    if (rel.startsWith('..') || isAbsolute(rel)) throw Error(`Source outside annotations: ${file}`);
    const source = read(file);
    return { page, file, source, ...compileAnnotation(source, page, config) };
  });
  const assertUnchanged = () => {
    for (const [file, text] of inputs) {
      if (readFileSync(file, 'utf8') !== text) throw Error(`Source changed during derivation: ${file}`);
    }
  };
  assertUnchanged();
  return { records, config, assertUnchanged };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const request = JSON.parse(readFileSync(0, 'utf8'));
  const { records } = readAnnotations(request.manifest, request.pages);
  process.stdout.write(JSON.stringify(records.map(({ page, ir, text, source_sha256 }) => ({ page, ir, text, source_sha256 }))));
}
