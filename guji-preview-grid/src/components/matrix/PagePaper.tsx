import type { CSSProperties, ReactNode } from "react";
import type { LayoutDiagnostic } from "@/ir/layout-diagnostics";
import "./page-paper.css";

export interface PagePaperLayout {
  width: number;
  minHeight: number;
  padding: { top: number; left: number; right: number };
  background?: string;
  unit: number;
  unitV: number;
}

/** 纸张负责页码、背景、边距和缩放变量；内部矩阵只负责版框与字格。 */
export function PagePaper({ pageNo, diagnostics, layout, children }: {
  pageNo: number;
  diagnostics: LayoutDiagnostic[];
  layout?: PagePaperLayout;
  children: ReactNode;
}) {
  const warnings = diagnostics.filter((d) => d.severity !== "info");
  return (
    <div
      data-paper
      className="page-paper"
      style={layout ? {
        width: layout.width,
        minHeight: layout.minHeight,
        paddingTop: layout.padding.top,
        paddingLeft: layout.padding.left,
        paddingRight: layout.padding.right,
        background: layout.background,
        "--guji-unit": `${layout.unit}px`,
        "--guji-unit-v": `${layout.unitV}px`,
      } as CSSProperties : undefined}
    >
      <div className="page-title" title={warnings.map((d) => d.message).join("；") || undefined}>
        {pageNo}{warnings.length > 0 && <span className="m-layout-warning" aria-label="版式需核对"> ⚠</span>}
      </div>
      {children}
    </div>
  );
}
