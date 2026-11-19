// 应用外壳：单行工具栏（左侧插槽=当前视图工具栏 portal 注入，右侧=视图切换）+ 当前视图。
// 校对 = 数据集对照工作流（扫描原图 | 刻本渲染 | .gj 编辑器 三列）；
// OCR 预取 = 调试视图（各页 OCR 结果对照 + prefetch_next_page 链路可视化）；
// 流程演示 = 添加新页管线逐步骤重放（初校页样例集 + 金标对照找错）。
// 原「编辑」双栏模式已移除；通用编辑/预览见姊妹项目 guji-preview
import { useState } from "react";
import { Toaster } from "sonner";
import {
  BookOpenText,
  ScanText,
  SquareTerminal,
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
import { useTheme } from "@/hooks/use-theme";
import { TOOLBAR_SLOT_ID } from "@/hooks/use-toolbar-slot";
import { useVimMode } from "@/hooks/use-vim-mode";

const VIEW_OPTIONS = [
  { value: "proof", label: "校对" },
  { value: "ocr", label: "OCR 预取" },
  { value: "pipeline", label: "流程演示" },
] as const;

type View = (typeof VIEW_OPTIONS)[number]["value"];

export default function App() {
  const { resolved } = useTheme();
  const vimMode = useVimMode();
  const [view, setView] = useState<View>("proof");

  return (
    <TooltipProvider>
      <div className="bg-background text-foreground flex h-svh flex-col">
        <header className="flex flex-wrap items-center gap-2 border-b px-3 py-1.5">
          {/* 左侧插槽：当前视图经 portal 注入各自工具栏（见 use-toolbar-slot） */}
          <div
            id={TOOLBAR_SLOT_ID}
            className="flex min-w-0 flex-1 flex-wrap items-center gap-2"
          />
          <div className="flex items-center gap-2">
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
      <Toaster
        theme={resolved}
        position="bottom-right"
        richColors
        closeButton
        duration={6000}
        containerAriaLabel="通知"
        toastOptions={{ closeButtonAriaLabel: "关闭通知" }}
      />
    </TooltipProvider>
  );
}
