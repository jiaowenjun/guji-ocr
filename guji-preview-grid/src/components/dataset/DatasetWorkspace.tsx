// 单页校对区：光标与尺寸状态留在三栏内部，数据集工具栏只响应文本和业务操作。
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Save, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { GujiEditor, type GujiEditorHandle } from "@/components/editor/GujiEditor";
import { MatrixPages } from "@/components/matrix/MatrixPages";
import { getPageFrame } from "@/ir/page-frame";
import { gj2ir } from "@/ir/gj2ir";
import { applyBookLayout } from "@/ir/document-layout";
import { layout3 } from "@/ir/layout3";
import { bandCursorTarget, buildCharIndex, charHighlightAt, highlightAt } from "@/ir/linkage";
import { resolvePageScan, type DatasetConfig } from "@/datasets/config";
import type { PageEntry } from "./DatasetView";

const SAVE_SHORTCUT_HINT = /Mac|iPod|iPhone|iPad/.test(navigator.platform) ? "⌘S" : "Ctrl+S";
const stem = (page: number) => String(page).padStart(4, "0");

/** 量取元素内容宽高（跟随面板拖动/窗口缩放）；回调 ref 模式：
 *  元素挂到 state 后才建立 ResizeObserver，规避挂载时序与节点重建问题 */
function useContentSize<T extends HTMLElement>() {
  const [el, setEl] = useState<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    if (!el) return;
    // 兜底初始尺寸：本环境（IAB/WKWebView）冷加载时 RO 的首次回调偶发丢失，
    // rAF 里主动量一次 content box；标签页不被绘制时 rAF 也会暂停，
    // 再加一次延时重读（后台标签页定时器仍触发）；RO 后续变化照常接管
    const read = () => {
      const cs = getComputedStyle(el);
      setSize({
        width: el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight),
        height: el.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom),
      });
    };
    const raf = requestAnimationFrame(read);
    const timer = setTimeout(read, 1200);
    const ro = new ResizeObserver(([entry]) =>
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height }),
    );
    ro.observe(el);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(timer);
      ro.disconnect();
    };
  }, [el]);
  return { ref: setEl, ...size };
}

function ColumnHeader({ children }: { children: ReactNode }) {
  // 单行截断：折行会让各栏头部行数不一，破坏左右栏滚动区顶边的对齐基准
  return (
    <div className="text-muted-foreground bg-background/60 border-b px-3 py-1 text-xs whitespace-nowrap overflow-hidden text-ellipsis">
      {children}
    </div>
  );
}

export function DatasetWorkspace({
  entry, config, text, originalLoaded, dirty, busy, rules, cells,
  editorTheme, vimMode, onChange, onSave, onReset, onFormat,
}: {
  entry?: PageEntry;
  config: DatasetConfig | null;
  text?: string;
  originalLoaded: boolean;
  dirty: boolean;
  busy: boolean;
  rules: boolean;
  cells: boolean;
  editorTheme: "light" | "dark";
  vimMode: boolean;
  onChange: (text: string) => void;
  onSave: () => void;
  onReset: () => void;
  onFormat: () => void;
}) {
  const page = entry?.page;
  // 每次文本更新只解析一次；布局、overlay 与联动共享同一份 IR。
  // ID 按结构位置生成，不能把新文本的高亮套到延迟更新的旧布局上。
  const irDoc = useMemo(() => {
    const parsed = gj2ir(text ?? "");
    return config ? applyBookLayout(parsed, config.layout) : parsed;
  }, [text, config]);
  const laidPages = useMemo(() => config ? layout3(irDoc) : [], [irDoc, config]);
  const frame = laidPages[0] ? getPageFrame(laidPages[0]) : null;
  const cols = frame?.cols ?? 0;

  // ---- 编辑器 ↔ 渲染列联动（当前 IR 的 src 偏移） ----
  const [cursor, setCursor] = useState<number | null>(null);
  const editorRef = useRef<GujiEditorHandle>(null);
  // 单字联动：charIndex 随文本重建（词法产物），光标移动只做二分定位
  const charIndex = useMemo(() => buildCharIndex(irDoc), [irDoc]);
  const highlight = useMemo(
    () => ({
      ...highlightAt(irDoc, cursor),
      char: charHighlightAt(charIndex, text ?? "", cursor),
    }),
    [irDoc, charIndex, text, cursor],
  );
  const onBandClick = useCallback(
    (p: number, i: number) => {
      const target = bandCursorTarget(irDoc, text ?? "", p, i);
      if (target !== null) editorRef.current?.revealPosition(target);
    },
    [irDoc, text],
  );
  // 渲染 unit 对齐版框内容宽（而非整图宽），矩阵视图下渲染页宽 = frameWidth

  // 原图列内容宽高 → 显示宽 → 渲染 unit（同宽联动）
  const { ref: scanRef, width: scanWidth, height: scanHeight } = useContentSize<HTMLDivElement>();
  // 始终按原图高度适配视口
  const displayWidth =
    entry && scanHeight > 0
      ? Math.floor((scanHeight * entry.width) / entry.height) // 向下取整，避免 1px 溢出触发滚动条
      : Math.max(200, scanWidth);
  // 等比纸边：渲染列包一层与扫描同尺寸的"纸"，内容区对齐版框
  const scan = config ? resolvePageScan(config, page ?? 0) : null;
  const scanMargin = scan?.margin ?? { left: 0, right: 0, top: 0, bottom: 0 };
  const scanScale = entry ? displayWidth / entry.width : 0;
  const paperPad = {
    left: scanMargin.left * scanScale,
    right: scanMargin.right * scanScale,
    top: scanMargin.top * scanScale,
    bottom: scanMargin.bottom * scanScale,
  };
  const frameWidth = displayWidth - paperPad.left - paperPad.right;

  // 纸面纵向：上 padding = 版框上边距等比值（内容顶边对齐版框上沿）；
  // 纸面本身顶天立地撑满渲染列视口（minHeight = 视口高 − p-2×2）。
  // 矩阵行高纵向微调：unit 由宽度反推（正方形格），行数 × unit 比版框内容高矮约 6%，
  // 行高单独放大到 版框内容高 ÷ 行数（--guji-unit-v），文字填满版框、底部无空白；
  // 列宽不变，左右版框对齐不受影响
  const { ref: scrollVPRef, height: scrollVPH } = useContentSize<HTMLDivElement>();
  const frameContentH = entry
    ? (entry.height - scanMargin.top - scanMargin.bottom) * scanScale
    : 0;
  const unit = cols > 0 ? (frameWidth - 2) / cols : 25;
  const matrixRows = frame?.rows ?? 0;
  // 固定整页行轨：短列不会被拉高；超高列仍裁剪并挂 m-over-mark 红条警示。
  const unitV = matrixRows > 0 ? frameContentH / matrixRows : unit;

  return (
    <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
      {/* 三栏默认宽度 2:2:3（原图:渲染:编辑器），可拖动调整 */}
      <ResizablePanel defaultSize={28.5} minSize={20}>
        <div className="flex h-full flex-col">
          <ColumnHeader>
            原图 · {entry?.image} · {entry ? `${entry.width}×${entry.height}` : ""} · 显示宽 {displayWidth}px
          </ColumnHeader>
          <div ref={scanRef} className="min-h-0 flex-1 overflow-auto bg-neutral-100 p-2 dark:bg-neutral-900">
            {entry ? (
              <div className="mx-auto" style={{ width: displayWidth }}>
                <img
                  src={`/dataset/images/${entry.image}`}
                  alt={`康熙字典 第 ${page} 页扫描图`}
                  className="block w-full select-none"
                  draggable={false}
                />
              </div>
            ) : null}
          </div>
        </div>
      </ResizablePanel>

      <ResizableHandle withHandle />

      <ResizablePanel defaultSize={28.5} minSize={20}>
        <div className="flex h-full flex-col">
          <ColumnHeader>
            矩阵 · {cols / (laidPages[0]?.config.smallColumnsPerBand ?? 1)} 大列 × {(frame?.rows ?? 0) / (laidPages[0]?.config.largeRows ?? 1)} 大字格 · 字格 {unit.toFixed(1)}px · 与原图版框对齐
          </ColumnHeader>
          <ScrollArea className="min-h-0 flex-1" ref={scrollVPRef}>
            <div className="flex justify-center p-2">
              {laidPages.length > 0 ? (
                <MatrixPages
                  pages={laidPages}
                  overlays={irDoc.overlays}
                  rules={rules}
                  cells={cells}
                  highlight={highlight}
                  onBandClick={onBandClick}
                  paper={{
                    width: displayWidth,
                    minHeight: Math.max(0, scrollVPH - 16),
                    padding: paperPad,
                    background: scan?.background,
                    unit,
                    unitV,
                  }}
                />
              ) : (
                <div className="text-muted-foreground flex h-96 flex-col items-center justify-center gap-2 text-sm">
                  <p>尚未解析出页面</p>
                  <p className="text-xs">编辑器内容需以 @页码 行开头</p>
                </div>
              )}
            </div>
          </ScrollArea>
        </div>
      </ResizablePanel>

      <ResizableHandle withHandle />

      <ResizablePanel defaultSize={43} minSize={20}>
        <div className="flex h-full flex-col">
          <ColumnHeader>
            .gj 编辑器 · @{page} · {dirty ? "未保存" : originalLoaded ? "与数据集一致" : "加载中…"}
          </ColumnHeader>
          {/* 编辑器工具栏：作用于 .gj 源码的快捷操作（格式化即保存；保存/重置针对未保存缓冲） */}
          <div className="flex flex-wrap items-center gap-2 border-b px-2 py-1">
            <Button
              size="sm"
              variant="outline"
              disabled={text === undefined || busy}
              onClick={onFormat}
              title="规范化为校对标准写法并自动保存：行内空格→*（半角连续空格合并为一个）；按语 ◎→〇；#（X）→#(X)；括号内 z→增、数字→汉字；#(X 补右括号；同行重复 # 合并、行首逗号回贴前行大字；按流式＋均式自动折行分列，保留 $ 强制换列；快捷键 Ctrl-⌥-F"
            >
              <Wand2 data-icon="inline-start" />
              格式化
            </Button>
            <Button
              size="sm"
              disabled={!dirty || busy}
              onClick={onSave}
              title={SAVE_SHORTCUT_HINT}
            >
              <Save data-icon="inline-start" />
              保存
            </Button>
            <Button size="sm" variant="outline" disabled={!dirty} onClick={onReset}>
              重置
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">
            {text !== undefined ? (
              <GujiEditor
                value={text}
                onChange={onChange}
                theme={editorTheme}
                onCursor={setCursor}
                ref={editorRef}
                onFormat={onFormat}
                vimMode={vimMode}
              />
            ) : (
              <div className="text-muted-foreground flex h-full items-center justify-center text-sm">
                正在加载 {stem(page ?? 0)}.gj…
              </div>
            )}
          </div>
        </div>
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}
