/** 通用结构：一个大列可分成两个小列，大字横跨整个大列。 */
export const GUJI_STRUCTURE = Object.freeze({ smallColumnsPerBand: 2 } as const);

/** 书籍版本的独立版式参数；小格高度比 1:n 用 n 个小格行表示。 */
export interface BookLayoutSpec {
  schemaVersion: 1;
  bandsPerPage: number;
  largeCellsPerBand: number;
  smallRowsPerLargeCell: number;
}

export interface LayoutPresetRef {
  id: string;
  revision: number;
}

export interface LayoutPreset extends LayoutPresetRef {
  spec: BookLayoutSpec;
}

export interface BookLayout {
  default: LayoutPreset;
  /** 页码选用完整预设，不做字段级合并，避免继承出不完整版式。 */
  pages?: Record<string, LayoutPreset>;
}

/** 持久化几何快照。保留 v1 自定义宽度和不定页宽，不追溯改写旧数据。 */
export interface IRLayoutConfig {
  version: 1;
  rowCap: number;
  /** null disables the fixed page width and its excess checks. */
  expectedBands: number | null;
  smallColumnsPerBand: number;
  largeRows: number;
  largeCols: number;
}

function positiveInteger(value: number, key: string) {
  if (!Number.isSafeInteger(value) || value <= 0)
    throw new Error(`layout.${key} must be a positive integer`);
}

/** 验证已有快照；通用层绝不隐含某本书的默认值。 */
export function resolveLayoutConfig(config: IRLayoutConfig | undefined): IRLayoutConfig {
  if (!config) throw new Error("Missing layout: select a book layout or explicitly import legacy data");
  if (config.version !== 1) throw new Error(`Unsupported layout version: ${config.version}`);
  for (const key of ["rowCap", "smallColumnsPerBand", "largeRows", "largeCols"] as const)
    positiveInteger(config[key], key);
  if (config.expectedBands !== null) positiveInteger(config.expectedBands, "expectedBands");
  return { ...config };
}

export function compileBookLayout(spec: BookLayoutSpec): IRLayoutConfig {
  if (!spec || spec.schemaVersion !== 1) throw new Error(`Unsupported book layout version: ${spec?.schemaVersion}`);
  for (const key of ["bandsPerPage", "largeCellsPerBand", "smallRowsPerLargeCell"] as const)
    positiveInteger(spec[key], key);
  positiveInteger(spec.bandsPerPage * GUJI_STRUCTURE.smallColumnsPerBand, "pageColumns");
  return resolveLayoutConfig({
    version: 1,
    expectedBands: spec.bandsPerPage,
    rowCap: spec.largeCellsPerBand * spec.smallRowsPerLargeCell,
    smallColumnsPerBand: GUJI_STRUCTURE.smallColumnsPerBand,
    largeCols: GUJI_STRUCTURE.smallColumnsPerBand,
    largeRows: spec.smallRowsPerLargeCell,
  });
}

export function resolveLayoutPreset(preset: LayoutPreset) {
  if (!preset || typeof preset.id !== "string" || !preset.id.trim())
    throw new Error("layout preset id is required");
  positiveInteger(preset.revision, "preset.revision");
  return {
    config: compileBookLayout(preset.spec),
    preset: { id: preset.id, revision: preset.revision } satisfies LayoutPresetRef,
  };
}

export function resolvePageLayout(book: BookLayout, pageNo: number) {
  return resolveLayoutPreset(book.pages?.[String(pageNo)] ?? book.default);
}
