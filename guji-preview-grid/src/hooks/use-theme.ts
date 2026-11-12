// 主题三态：自动跟随系统 / 亮 / 暗。localStorage 持久化（guji-theme），默认自动。
// 应用方式：<html> 上切换 .dark 类（Tailwind v4 @custom-variant dark + shadcn 令牌组）。
import { useCallback, useEffect, useState } from "react";

export type ThemeSetting = "auto" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "guji-theme";

function readSetting(): ThemeSetting {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : "auto";
  } catch {
    return "auto";
  }
}

export function useTheme() {
  const [setting, setSetting] = useState<ThemeSetting>(readSetting);
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = setting === "auto" ? mq.matches : setting === "dark";
      document.documentElement.classList.toggle("dark", dark);
      setResolved(dark ? "dark" : "light");
    };
    apply();
    if (setting === "auto") {
      mq.addEventListener("change", apply); // 跟随系统切换
      return () => mq.removeEventListener("change", apply);
    }
  }, [setting]);

  const update = useCallback((s: ThemeSetting) => {
    try {
      localStorage.setItem(STORAGE_KEY, s);
    } catch {
      /* 隐私模式等存储失败时仅内存生效 */
    }
    setSetting(s);
  }, []);

  return { setting, resolved, update };
}
