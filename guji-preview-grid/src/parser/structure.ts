/** Standalone chunk only. Legacy # remains a compatible empty-column spelling. */
export function isBlankBand(source: string): boolean {
  return /^(?:@blank|#)\s*(?:\/\/[^\r\n]*)?$/.test(source.trim());
}
