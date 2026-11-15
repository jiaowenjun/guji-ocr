// 编辑器 vim 模式开关：localStorage 持久化（guji-vim），默认关闭。
// 开启后 GujiEditor 挂载 @replit/codemirror-vim（normal/insert 双模态，
// normal 为初始模态，i/a/A/o/O/c/C 等进入 insert，Esc 返回）。
import { useCallback, useState } from "react";

const STORAGE_KEY = "guji-vim";

function readSetting(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "on";
  } catch {
    return false;
  }
}

export function useVimMode() {
  const [enabled, setEnabled] = useState(readSetting);

  const update = useCallback((v: boolean) => {
    try {
      localStorage.setItem(STORAGE_KEY, v ? "on" : "off");
    } catch {
      /* 隐私模式等存储失败时仅内存生效 */
    }
    setEnabled(v);
  }, []);

  return { enabled, update };
}
