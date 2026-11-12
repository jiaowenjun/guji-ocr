// 移植自 vscode-guji-preview/src/components/page.ts
// 一页：页码标题 + 右起的行（lines）
import type { PageModel } from "./model";
import { activeBookFrags, type RenderHighlight } from "./Pages";
import { Line } from "./Line";

export function Page({
  pageModel,
  highlight,
  onBandClick,
}: {
  pageModel: PageModel;
  highlight?: RenderHighlight;
  onBandClick?: (page: number, index: number) => void;
}) {
  return (
    <div className="page">
      <div className="page-title">{pageModel.p}</div>
      <div className="lines">
        {pageModel.l.map((l, i) => (
          <Line
            key={i}
            model={l}
            active={highlight?.band?.page === pageModel.p && highlight.band.index === i}
            activeBooks={activeBookFrags("c" in l ? l.c : undefined, highlight, pageModel.p, i)}
            onClick={onBandClick ? () => onBandClick(pageModel.p, i) : undefined}
          />
        ))}
      </div>
    </div>
  );
}
