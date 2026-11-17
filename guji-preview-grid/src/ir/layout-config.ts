/** Versioned cell geometry; independent of transcription/cleaning rules. */
export interface IRLayoutConfig {
  version: 1;
  rowCap: number;
  /** Full page width in bands; fewer bands leave whitespace. null disables this frame and its excess checks. */
  expectedBands: number | null;
  smallColumnsPerBand: number;
  largeRows: number;
  largeCols: number;
}

export const KANGXI_LAYOUT: Readonly<IRLayoutConfig> = Object.freeze({
  version: 1,
  rowCap: 24,
  expectedBands: 8,
  smallColumnsPerBand: 2,
  largeRows: 2,
  largeCols: 2,
});

export function resolveLayoutConfig(config: IRLayoutConfig = KANGXI_LAYOUT): IRLayoutConfig {
  if (config.version !== 1) throw new Error(`Unsupported layout version: ${config.version}`);
  for (const key of ["rowCap", "smallColumnsPerBand", "largeRows", "largeCols"] as const) {
    if (!Number.isSafeInteger(config[key]) || config[key] <= 0)
      throw new Error(`layout.${key} must be a positive integer`);
  }
  if (config.expectedBands !== null && (!Number.isSafeInteger(config.expectedBands) || config.expectedBands <= 0))
    throw new Error("layout.expectedBands must be null or a positive integer");
  return { ...config };
}
