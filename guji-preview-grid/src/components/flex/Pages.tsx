// 移植自 vscode-guji-preview/src/components/pages.ts
// 多页文档容器；缩放基准 --guji-unit 挂在 .pages 上（见 flex.css）
import type { PageModel, BlockModel } from "./model";
import { bandKey, type RenderHighlight } from "../../parser/locate";
import { Page } from "./Page";

export type { RenderHighlight };

export function Pages({
  pageModels,
  highlight,
  onBandClick,
}: {
  pageModels: PageModel[];
  highlight?: RenderHighlight;
  onBandClick?: (page: number, index: number) => void;
}) {
  return (
    <div className="pages">
      {pageModels.map((pageModel, i) => (
        <Page key={i} pageModel={pageModel} highlight={highlight} onBandClick={onBandClick} />
      ))}
    </div>
  );
}

/** 计算某大行内需高亮的书名块集合（片段序号与渲染顺序一致） */
export function activeBookFrags(
  blocks: BlockModel[] | undefined,
  highlight: RenderHighlight | undefined,
  page: number,
  bandIndex: number,
): Set<BlockModel> {
  const set = new Set<BlockModel>();
  const runs = highlight?.book?.[bandKey(page, bandIndex)];
  if (!runs?.length || !blocks) return set;
  let ord = 0;
  for (const blk of blocks) {
    if (blk.st?.startsWith("book") && blk.t) {
      if (runs.some((r) => ord >= r.start && ord < r.start + r.count)) set.add(blk);
      ord++;
    }
  }
  return set;
}
