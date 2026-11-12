// 移植自 vscode-guji-preview/src/components/small-line.ts
// 一列小字：普通片段逐字入格，书名片段交给 Book
import type { BlockModel } from "./model";
import { Book } from "./Book";
import { Grid } from "./Grid";

export function SmallLine({
  frags,
  activeBooks,
}: {
  frags: BlockModel[];
  activeBooks?: Set<BlockModel>;
}) {
  return (
    <div className="small-line">
      {frags.map((frag, i) => {
        if (frag.st && frag.st.startsWith("book") && frag.t) {
          return (
            <Book
              key={i}
              text={frag.t}
              style={frag.st}
              active={activeBooks?.has(frag)}
            />
          );
        } else if (frag.t) {
          return [...frag.t].map((letter, j) => (
            <Grid key={`${i}-${j}`} letter={letter} />
          ));
        }
        return null;
      })}
    </div>
  );
}
