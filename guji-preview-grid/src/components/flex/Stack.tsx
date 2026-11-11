// 移植自 vscode-guji-preview/src/components/stack.ts
// 两字合成的带圈大字经此容器叠排，由 .large-circle .stack 样式纵向压扁
export function Stack({ letter }: { letter: string }) {
  return <div className="stack">{letter}</div>;
}
