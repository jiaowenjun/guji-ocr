// 移植自 vscode-guji-preview/src/components/large-circle.ts
// 带圈大字列，text 作为单个“字符”放入一格（两字合成时该格内为 Stack）
import { Grid } from "./Grid";

export function LargeCircle({
  text,
  indent,
}: {
  text: string;
  indent: number;
}) {
  const indentText = [..." ".repeat(indent), text];
  return (
    <div className="large-circle">
      {indentText.map((letter, i) => (
        <Grid key={i} letter={letter} />
      ))}
    </div>
  );
}
