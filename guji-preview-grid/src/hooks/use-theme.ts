// 主题跟随系统：监听 prefers-color-scheme，resolved 供编辑器主题联动。
// 应用方式：<html> 上切换 .dark 类（Tailwind v4 @custom-variant dark + shadcn 令牌组）。
import { useEffect, useState } from "react";

export type ResolvedTheme = "light" | "dark";

export function useTheme() {
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
  );

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.classList.toggle("dark", mq.matches);
      setResolved(mq.matches ? "dark" : "light");
    };
    apply();
    mq.addEventListener("change", apply); // 跟随系统切换
    return () => mq.removeEventListener("change", apply);
  }, []);

  return { resolved };
}
