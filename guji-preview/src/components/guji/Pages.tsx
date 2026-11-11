// 移植自 vscode-guji-preview/src/components/pages.ts
// 多页文档容器；缩放基准 --guji-unit 挂在 .pages 上（见 guji.css）
import type { PageModel } from "./model";
import { Page } from "./Page";

export function Pages({ pageModels }: { pageModels: PageModel[] }) {
  return (
    <div className="pages">
      {pageModels.map((pageModel, i) => (
        <Page key={i} pageModel={pageModel} />
      ))}
    </div>
  );
}
