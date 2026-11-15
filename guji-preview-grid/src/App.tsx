// 应用外壳：顶部标题栏（视图切换 + 主题切换 + 字体说明）+ 当前视图。
// 校对 = 数据集对照工作流（扫描原图 | 刻本渲染 | .gj 编辑器 三列）；
// OCR 预取 = 调试视图（各页 OCR 结果对照 + prefetch_next_page 链路可视化）；
// 流程演示 = 添加新页管线逐步骤重放（初校页样例集 + 金标对照找错）。
// 原「编辑」双栏模式已移除；通用编辑/预览见姊妹项目 guji-preview
import { useState } from "react";
import {
  BookOpenText,
  Info,
  Monitor,
  Moon,
  ScanText,
  SquareTerminal,
  Sun,
  Workflow,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { DatasetView } from "@/components/dataset/DatasetView";
import { OcrPrefetchView } from "@/components/ocr/OcrPrefetchView";
import { PipelineReplayView } from "@/components/ocr/PipelineReplayView";
import { useTheme, type ThemeSetting } from "@/hooks/use-theme";
import { useVimMode } from "@/hooks/use-vim-mode";

const THEME_OPTIONS: { value: ThemeSetting; label: string; icon: typeof Sun }[] = [
  { value: "auto", label: "跟随系统", icon: Monitor },
  { value: "light", label: "浅色", icon: Sun },
  { value: "dark", label: "深色", icon: Moon },
];

const VIEW_OPTIONS = [
  { value: "proof", label: "校对" },
  { value: "ocr", label: "OCR 预取" },
  { value: "pipeline", label: "流程演示" },
] as const;

type View = (typeof VIEW_OPTIONS)[number]["value"];

export default function App() {
  const { setting, resolved, update } = useTheme();
  const vimMode = useVimMode();
  const [view, setView] = useState<View>("proof");

  return (
    <TooltipProvider>
      <div className="bg-background text-foreground flex h-svh flex-col">
        <header className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
          <BookOpenText className="text-primary size-5" />
          <h1 className="text-base font-semibold">古籍预览</h1>
          <span className="text-muted-foreground text-xs">guji-preview-grid</span>

          <div className="ml-auto flex items-center gap-2">
            <div className="border-border flex items-center gap-1 rounded-lg border p-0.5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon-sm"
                    variant={view === "proof" ? "default" : "ghost"}
                    aria-label="校对视图"
                    aria-pressed={view === "proof"}
                    onClick={() => setView("proof")}
                  >
                    <BookOpenText />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>校对（数据集对照工作流）</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon-sm"
                    variant={view === "ocr" ? "default" : "ghost"}
                    aria-label="OCR 预取视图"
                    aria-pressed={view === "ocr"}
                    onClick={() => setView("ocr")}
                  >
                    <ScanText />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>OCR 预取（各页 OCR 结果 + 预取链路调试）</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon-sm"
                    variant={view === "pipeline" ? "default" : "ghost"}
                    aria-label="流程演示视图"
                    aria-pressed={view === "pipeline"}
                    onClick={() => setView("pipeline")}
                  >
                    <Workflow />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  流程演示（添加新页管线逐步骤重放，初校页样例集 + 金标对照找错）
                </TooltipContent>
              </Tooltip>
            </div>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="icon-sm"
                  variant={vimMode.enabled ? "default" : "ghost"}
                  aria-label="Vim 模式"
                  aria-pressed={vimMode.enabled}
                  onClick={() => vimMode.update(!vimMode.enabled)}
                >
                  <SquareTerminal />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                vim 模式（默认关）：normal/insert 双模态，i/a/A/o/O/c/C 进入
                insert，Esc 返回 normal；insert 模态保留 emacs/Alt 快捷键
              </TooltipContent>
            </Tooltip>

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

        {view === "proof" ? (
          <DatasetView editorTheme={resolved} vimMode={vimMode.enabled} />
        ) : view === "ocr" ? (
          <OcrPrefetchView />
        ) : (
          <PipelineReplayView />
        )}
      </div>
    </TooltipProvider>
  );
}
