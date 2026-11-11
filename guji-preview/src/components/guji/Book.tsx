// 移植自 vscode-guji-preview/src/components/book.ts
// 行内书名框；跨行书名拆为 book-start / book-middle / book-end 相邻拼接
import { Grid } from "./Grid";

export function Book({ text, style }: { text: string; style: string }) {
  return (
    <div className={style === "book" ? "book" : `book ${style}`}>
      {[...text].map((letter, i) => (
        <Grid key={i} letter={letter} />
      ))}
    </div>
  );
}
