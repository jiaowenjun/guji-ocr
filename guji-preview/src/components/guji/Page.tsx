// 移植自 vscode-guji-preview/src/components/page.ts
// 一页：页码标题 + 右起的行（lines）
import type { PageModel } from "./model";
import { Line } from "./Line";

export function Page({ pageModel }: { pageModel: PageModel }) {
  return (
    <div className="page">
      <div className="page-title">{pageModel.p}</div>
      <div className="lines">
        {pageModel.l.map((l, i) => (
          <Line key={i} model={l} />
        ))}
      </div>
    </div>
  );
}
