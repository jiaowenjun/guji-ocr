// 应用外壳：顶部标题栏（主题切换 + 字体说明）+ 数据集对照视图
// （扫描原图 | 刻本渲染 | .gj 编辑器 三列）
// 原「编辑」双栏模式已移除，应用专注重复校对工作流；通用编辑/预览见姊妹项目 guji-preview
import { BookOpenText, Info, Monitor, Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { DatasetView } from "@/components/dataset/DatasetView";
import { useTheme, type ThemeSetting } from "@/hooks/use-theme";

const THEME_OPTIONS: { value: ThemeSetting; label: string; icon: typeof Sun }[] = [
  { value: "auto", label: "跟随系统", icon: Monitor },
  { value: "light", label: "浅色", icon: Sun },
  { value: "dark", label: "深色", icon: Moon },
];

export default function App() {
  const { setting, resolved, update } = useTheme();

  return (
    <TooltipProvider>
      <div className="bg-background text-foreground flex h-svh flex-col">
        <header className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
          <BookOpenText className="text-primary size-5" />
          <h1 className="text-base font-semibold">古籍预览</h1>
          <span className="text-muted-foreground text-xs">guji-preview-grid</span>

          <div className="ml-auto flex items-center gap-2">
            <div className="border-border flex items-center gap-1 rounded-lg border p-0.5">
              {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
                <Tooltip key={value}>
                  <TooltipTrigger asChild>
                    <Button
                      size="icon-sm"
                      variant={setting === value ? "default" : "ghost"}
                      aria-label={label}
                      aria-pressed={setting === value}
                      onClick={() => update(value)}
                    >
                      <Icon />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    {label}
                    {value === "auto" ? `（当前：${resolved === "dark" ? "深色" : "浅色"}）` : ""}
                  </TooltipContent>
                </Tooltip>
              ))}
            </div>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label="字体说明">
                  <Info />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-72">
                <p>刻本渲染需本地安装两款字体：</p>
                <p>大字：康熙傳承版 KangXiZiDian.com</p>
                <p>小字：中華書局宋體 00/02/15 平面</p>
                <p className="text-muted-foreground">
                  下载方式见项目 README；未安装时以 serif 回退显示。
                </p>
              </TooltipContent>
            </Tooltip>
          </div>
        </header>

        <DatasetView editorTheme={resolved} />
      </div>
    </TooltipProvider>
  );
}
