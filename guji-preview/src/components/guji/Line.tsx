// 移植自 vscode-guji-preview/src/components/line.ts
// 一列（大行）：复合行按块分组——连续小字片段归为 SmallLine/Small，
// 大字块作为兄弟节点；分组算法保持原版一致
import type { ReactNode } from "react";
import type { BlockModel, LineModel } from "./model";
import { Large } from "./Large";
import { LargeCircle } from "./LargeCircle";
import { Small } from "./Small";
import { SmallLine } from "./SmallLine";

function parseLineBlocks(blks: BlockModel[]): ReactNode[] {
  const nodes: ReactNode[] = [];
  let smallLines: ReactNode[] = [];
  let frags: BlockModel[] = [];

  const mergeFrags = () => {
    if (frags.length > 0) {
      smallLines.push(<SmallLine key={smallLines.length} frags={frags} />);
      frags = [];
    }
  };

  const mergeSmallLines = () => {
    if (smallLines.length > 0) {
      nodes.push(<Small key={nodes.length}>{smallLines}</Small>);
      smallLines = [];
    }
  };

  blks.forEach((blk) => {
    if (blk.si === "large" && blk.t) {
      mergeFrags();
      mergeSmallLines();
      if (blk.st === "circle") {
        nodes.push(
          <LargeCircle key={nodes.length} text={blk.t} indent={blk.i ? blk.i : 0} />
        );
      } else {
        nodes.push(
          <Large key={nodes.length} text={blk.t} indent={blk.i ? blk.i : 0} />
        );
      }
    } else {
      if (blk.st === "br") {
        mergeFrags();
      } else {
        frags.push(blk);
      }
    }
  });

  mergeFrags();
  mergeSmallLines();

  return nodes;
}

export function Line({ model }: { model: LineModel }) {
  if ("c" in model) {
    return <div className="line">{parseLineBlocks(model.c)}</div>;
  } else if (model.si === "large" && model.t) {
    return (
      <div className="line">
        <Large text={model.t} indent={model.i ? model.i : 0} />
      </div>
    );
  } else if (model.st === "empty") {
    return (
      <div className="line">
        <Large text=" " indent={0} />
      </div>
    );
  } else {
    return null;
  }
}
