// 工具栏插槽：App 壳层单行工具栏左侧的挂载点。各视图经 portal 把自己的
// 工具栏注入进来，与右侧全局工具（视图切换等）合并为一行，节省纵向空间。
// useLayoutEffect 在首帧绘制前定位插槽，避免工具栏闪现一帧空缺。
import { useLayoutEffect, useState } from "react";

export const TOOLBAR_SLOT_ID = "app-toolbar-slot";

export function useToolbarSlot() {
  const [el, setEl] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => {
    setEl(document.getElementById(TOOLBAR_SLOT_ID));
  }, []);
  return el;
}
