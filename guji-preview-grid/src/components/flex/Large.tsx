// 移植自 vscode-guji-preview/src/components/large.ts
// 整列大字（字头/标题），逐字一格
import { Grid } from "./Grid";

export function Large({ text, indent }: { text: string; indent: number }) {
  const indentText = " ".repeat(indent) + text;
  return (
    <div className="large">
      {[...indentText].map((letter, i) => (
        <Grid key={i} letter={letter} />
      ))}
    </div>
  );
}
