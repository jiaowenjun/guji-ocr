// 移植自 vscode-guji-preview/src/components/book.ts
// 行内书名框；跨行书名拆为 book-start / book-middle / book-end 相邻拼接
import { Grid } from "./Grid";

export function Book({ text, style, active }: { text: string; style: string; active?: boolean }) {
  const cls = [style === "book" ? "book" : `book ${style}`, active && "book-active"]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls}>
      {[...text].map((letter, i) => (
        <Grid key={i} letter={letter} />
      ))}
    </div>
  );
}
