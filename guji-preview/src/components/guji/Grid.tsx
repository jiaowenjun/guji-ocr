// 移植自 vscode-guji-preview/src/components/grid.ts
// 单个字符格；length > 1 的“字符”（如 UTF-16 代理对或两字合成串）包一层 Stack
import { Stack } from "./Stack";

export function Grid({ letter }: { letter: string }) {
  return (
    <div className="grid">
      {letter.length > 1 ? <Stack letter={letter} /> : letter}
    </div>
  );
}
