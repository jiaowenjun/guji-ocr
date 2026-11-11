// 应用外壳：顶部工具栏 + 左编辑右预览双栏
import { useMemo, useRef, useState, type CSSProperties } from "react";
import { BookOpenText, Download, FileUp, Info, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { GujiEditor } from "@/components/editor/GujiEditor";
import { Pages } from "@/components/guji/Pages";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { downloadHtml } from "@/lib/export-html";
import { parsePages } from "@/parser/parse-pages";
import { samples } from "@/samples";

const DEFAULT_SCALE = 25;

export default function App() {
  const [text, setText] = useState(samples[0].content);
  const [scale, setScale] = useState(DEFAULT_SCALE);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const debouncedText = useDebouncedValue(text, 200);
  const pages = useMemo(() => parsePages(debouncedText), [debouncedText]);

  const openFile = async (file: File) => {
    setText(await file.text());
  };

  return (
    <TooltipProvider>
      <div className="bg-background text-foreground flex h-svh flex-col">
        <header className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
          <BookOpenText className="text-primary size-5" />
          <h1 className="text-base font-semibold">古籍预览</h1>
          <span className="text-muted-foreground text-xs">guji-preview</span>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm">
                  示例
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>内置文档</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {samples.map((s) => (
                  <DropdownMenuItem key={s.id} onClick={() => setText(s.content)}>
                    <div className="flex flex-col">
                      <span>{s.name}</span>
                      <span className="text-muted-foreground text-xs">
                        {s.description}
                      </span>
                    </div>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
            >
              <FileUp data-icon="inline-start" />
              打开文件
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".gj,text/plain"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) openFile(file);
                e.target.value = "";
              }}
            />

            <Separator orientation="vertical" className="h-5" />

            <div className="flex items-center gap-2">
              <span className="text-muted-foreground text-xs">缩放</span>
              <Slider
                value={[scale]}
                onValueChange={([v]) => setScale(v)}
                min={12}
                max={48}
                step={1}
                className="w-28"
              />
              <span className="text-muted-foreground w-12 text-xs tabular-nums">
                {scale} px
              </span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="重置缩放"
                    onClick={() => setScale(DEFAULT_SCALE)}
                  >
                    <RotateCcw />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>重置缩放</TooltipContent>
              </Tooltip>
            </div>

            <Separator orientation="vertical" className="h-5" />

            <Button
              size="sm"
              disabled={pages.length === 0}
              onClick={() => downloadHtml(pages, "guji.html", scale)}
            >
              <Download data-icon="inline-start" />
              导出 HTML
            </Button>

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

        <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
          <ResizablePanel defaultSize={38} minSize={22}>
            <div className="h-full overflow-hidden">
              <GujiEditor value={text} onChange={setText} />
            </div>
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={62}>
            <div className="flex h-full flex-col">
              <div className="text-muted-foreground border-b bg-white/60 px-4 py-1 text-xs">
                共 {pages.length} 页
              </div>
              <ScrollArea className="min-h-0 flex-1">
                <div
                  className="flex justify-center p-8"
                  style={{ "--guji-scale": `${scale}px` } as CSSProperties}
                >
                  {pages.length > 0 ? (
                    <Pages pageModels={pages} />
                  ) : (
                    <div className="text-muted-foreground flex h-96 flex-col items-center justify-center gap-2 text-sm">
                      <BookOpenText className="size-10 opacity-30" />
                      <p>尚未解析出任何页面</p>
                      <p className="text-xs">
                        Guji 文档需包含「@页码」声明行（如{" "}
                        <code className="bg-muted rounded px-1">@312</code>
                        ），其后的内容才会渲染
                      </p>
                    </div>
                  )}
                </div>
              </ScrollArea>
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </TooltipProvider>
  );
}
