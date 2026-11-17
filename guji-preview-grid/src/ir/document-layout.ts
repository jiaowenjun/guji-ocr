import { resolveLayoutConfig, resolveLayoutPreset, resolvePageLayout, type BookLayout } from "./layout-config";
import type { IRDocument } from "./types";

/** 为新解析的文档明确选用书籍版式；保存数值快照，无需预设注册表也能复现。
 *  已有快照的文档应直接布局，切换书籍版式时才显式重新调用此函数。 */
export function applyBookLayout(doc: IRDocument, book: BookLayout): IRDocument {
  const base = resolveLayoutPreset(book.default);
  return {
    ...doc,
    meta: { ...doc.meta, layout: base.config, layoutPreset: base.preset },
    pages: doc.pages.map((page) => {
      const { layout: _layout, layoutPreset: _preset, ...content } = page;
      if (!book.pages?.[String(page.no)]) return content;
      const selected = resolvePageLayout(book, page.no);
      return { ...content, layout: selected.config, layoutPreset: selected.preset };
    }),
  };
}

/** 只补无配置的旧数据；调用方必须先确认书籍身份。已有 v1 快照原样验证保留。 */
export function importLegacyLayout(doc: IRDocument, book: BookLayout): IRDocument {
  const hasDefault = doc.meta.layout !== undefined;
  const fallback = hasDefault ? doc : applyBookLayout(doc, book);
  return {
    ...doc,
    meta: hasDefault ? { ...doc.meta, layout: resolveLayoutConfig(doc.meta.layout) } : fallback.meta,
    pages: doc.pages.map((page, i) => page.layout !== undefined
      ? { ...page, layout: resolveLayoutConfig(page.layout) }
      : hasDefault ? { ...page } : fallback.pages[i]),
  };
}
