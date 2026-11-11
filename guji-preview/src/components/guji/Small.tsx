// 移植自 vscode-guji-preview/src/components/small.ts
// 大字旁的一组小字列（右起）
import type { ReactNode } from "react";

export function Small({ children }: { children: ReactNode }) {
  return <div className="small">{children}</div>;
}
