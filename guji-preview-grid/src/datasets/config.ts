import { resolveLayoutPreset, type BookLayout } from "../ir/layout-config";

export interface ScanGeometry {
  /** 当前扫描原图的自然像素；与书籍的逻辑格数无关。 */
  margin: { left: number; top: number; right: number; bottom: number };
  background: string;
}

export interface DatasetConfig {
  schemaVersion: 1;
  id: string;
  title: string;
  layout: BookLayout;
  scan: ScanGeometry;
  scanPages?: Record<string, ScanGeometry>;
}

function validateScan(scan: ScanGeometry) {
  if (!scan?.margin || typeof scan.background !== "string" || !/^#[\da-f]{6}$/i.test(scan.background))
    throw new Error("Invalid scan geometry or background");
  for (const side of ["left", "top", "right", "bottom"] as const)
    if (!Number.isFinite(scan.margin[side]) || scan.margin[side] < 0)
      throw new Error(`scan.margin.${side} must be nonnegative`);
}

/** JSON 边界统一验证，未知数据集不回落到康熙参数。 */
export function resolveDatasetConfig(input: unknown): DatasetConfig {
  const config = input as DatasetConfig;
  if (!config || config.schemaVersion !== 1) throw new Error("Unsupported dataset config version");
  if (typeof config.id !== "string" || !config.id.trim() || typeof config.title !== "string")
    throw new Error("Dataset id and title are required");
  resolveLayoutPreset(config.layout?.default);
  for (const [page, preset] of Object.entries(config.layout.pages ?? {})) {
    if (!/^\d+$/.test(page) || !Number.isSafeInteger(Number(page)) || String(Number(page)) !== page) throw new Error(`Invalid layout page: ${page}`);
    resolveLayoutPreset(preset);
  }
  validateScan(config.scan);
  for (const [page, scan] of Object.entries(config.scanPages ?? {})) {
    if (!/^\d+$/.test(page) || !Number.isSafeInteger(Number(page)) || String(Number(page)) !== page) throw new Error(`Invalid scan page: ${page}`);
    validateScan(scan);
  }
  return structuredClone(config);
}

export function resolvePageScan(config: DatasetConfig, pageNo: number): ScanGeometry {
  return config.scanPages?.[String(pageNo)] ?? config.scan;
}
