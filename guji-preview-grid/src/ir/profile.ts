import type { IRProfile } from "./types";

export interface CleanedText {
  cells: string[];
  /** Each output codepoint refers to a half-open range of input codepoints. */
  ranges: Array<[number, number]>;
}

/** Compile once per document. Rules run in order, matching Python str.replace. */
export function compileProfile(profile: IRProfile): (text: string) => CleanedText {
  if (profile.stripPunct.some((s) => [...s].length !== 1))
    throw new Error("profile.stripPunct entries must be single codepoints");
  const strip = new Set(profile.stripPunct);
  const rules = profile.normalize.map(([from, to]) => {
    if (!from) throw new Error("profile.normalize cannot replace an empty string");
    return { from: [...from], to: [...to] };
  });
  return (text) => {
    let units = [...text].map((ch, i) => ({ ch, range: [i, i + 1] as [number, number] }));
    for (const { from, to } of rules) {
      const next: typeof units = [];
      for (let i = 0; i < units.length;) {
        if (from.every((ch, j) => units[i + j]?.ch === ch)) {
          const range: [number, number] = [units[i].range[0], units[i + from.length - 1].range[1]];
          for (const ch of to) next.push({ ch, range });
          i += from.length;
        } else next.push(units[i++]);
      }
      units = next;
    }
    units = units.filter(({ ch }) => !strip.has(ch));
    return { cells: units.map((u) => u.ch), ranges: units.map((u) => u.range) };
  };
}
