// 数据集对照视图：扫描原图 | 刻本渲染 | .gj 编辑器 三列对照
// 数据访问层由 scripts/link-dataset.sh 生成（public/dataset/ 符号链接 + index.json），
// 保存经 vite.config.ts 的 datasetSave dev 中间件写回 kangxi-gold/annotations/NNNN.gj。
// 渲染列宽度跟随原图列显示宽：unit = (显示宽 − 2px) / 横向字格数（pageColumns）。
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { ChevronLeft, ChevronRight, Database, Download, RotateCcw, Save } from "lucide-react";
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
import { GujiEditor } from "@/components/editor/GujiEditor";
import { Pages as FlexPages } from "@/components/flex/Pages";
import { MatrixPages, pageColumns } from "@/components/matrix/MatrixPages";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { layoutPages } from "@/matrix/layout";
import { parsePages } from "@/parser/parse-pages";

interface PageEntry {
  page: number;
  image: string;
  gj: string;
  width: number;
  height: number;
}

const stem = (page: number) => String(page).padStart(4, "0");

/** 量取元素内容宽（跟随面板拖动/窗口缩放）；回调 ref 模式：
 *  元素挂到 state 后才建立 ResizeObserver，规避挂载时序与节点重建问题 */
function useContentWidth<T extends HTMLElement>() {
  const [el, setEl] = useState<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(el); // observe 时按规范会先发一次当前尺寸回调
    return () => ro.disconnect();
  }, [el]);
  return { ref: setEl, width };
}

/** 页清单（public/dataset/index.json） */
function useDatasetIndex() {
  const [index, setIndex] = useState<PageEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetch("/dataset/index.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: { pages: PageEntry[] }) => alive && setIndex(data.pages))
      .catch((e: unknown) =>
        alive && setError(e instanceof Error ? e.message : String(e)),
      );
    return () => {
      alive = false;
    };
  }, []);
  return { index, error };
}

/** 各页 .gj 原文缓存；ensure() 缺失即取（含预取），失败页可重试 */
function useDatasetText() {
  const [texts, setTexts] = useState<Record<number, string>>({});
  const textsRef = useRef(texts);
  const pending = useRef(new Set<number>());
  const ensure = useCallback((pages: number[]) => {
    for (const page of pages) {
      if (page in textsRef.current || pending.current.has(page)) continue;
      pending.current.add(page);
      fetch(`/dataset/annotations/${stem(page)}.gj`)
        .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
        .then((text) => {
          textsRef.current[page] = text;
          setTexts({ ...textsRef.current });
        })
        .catch(() => {
          pending.current.delete(page);
        });
    }
  }, []);
  const put = useCallback((page: number, text: string) => {
    textsRef.current[page] = text;
    setTexts({ ...textsRef.current });
  }, []);
  return { texts, ensure, put };
}

function ColumnHeader({ children }: { children: ReactNode }) {
  return (
    <div className="text-muted-foreground border-b bg-white/60 px-3 py-1 text-xs">
      {children}
    </div>
  );
}

export function DatasetView() {
  const { index, error } = useDatasetIndex();
  const [idx, setIdx] = useState(0);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const { texts, ensure, put } = useDatasetText();
  const [rules, setRules] = useState(true);
  const [flexView, setFlexView] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);

  const entry = index?.[idx];
  const page = entry?.page;
  const original = page !== undefined ? texts[page] : undefined;
  const text = page !== undefined ? (edits[page] ?? original) : undefined;
  const dirty = page !== undefined && edits[page] !== undefined && edits[page] !== original;

  // 当前页 + 相邻页预取
  useEffect(() => {
    if (!index) return;
    ensure([index[idx]?.page, index[idx - 1]?.page, index[idx + 1]?.page].filter(
      (p): p is number => p !== undefined,
    ));
  }, [index, idx, ensure]);

  // ←/→ 翻页（编辑器/表单聚焦时不劫持）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!index || (e.target as HTMLElement | null)?.closest(".cm-editor, input, textarea, select")) return;
      if (e.key === "ArrowRight" && idx < index.length - 1) setIdx(idx + 1);
      if (e.key === "ArrowLeft" && idx > 0) setIdx(idx - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, idx]);

  const debouncedText = useDebouncedValue(text ?? "", 200);
  const pageModels = useMemo(() => parsePages(debouncedText), [debouncedText]);
  const matrixPages = useMemo(() => layoutPages(pageModels), [pageModels]);
  const cols = matrixPages[0] ? pageColumns(matrixPages[0]) : 0;

  // 原图列内容宽 → 显示宽（缩放百分比）→ 渲染 unit（同宽联动）
  const { ref: scanRef, width: scanWidth } = useContentWidth<HTMLDivElement>();
  const displayWidth = Math.max(200, Math.round((scanWidth * zoom) / 100));
  const unit = cols > 0 ? (displayWidth - 2) / cols : 25;

  const onChange = useCallback(
    (value: string) => {
      if (page === undefined) return;
      setEdits((prev) => ({ ...prev, [page]: value }));
    },
    [page],
  );

  const reset = () => {
    if (page === undefined) return;
    setEdits(({ [page]: _drop, ...rest }) => rest);
    setStatus(null);
  };

  const save = async () => {
    if (page === undefined || text === undefined) return;
    setBusy(true);
    setStatus(null);
    try {
      const res = await fetch("/dataset/save", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ page, content: text }),
      });
      const data = (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string };
      if (!res.ok || !data.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      put(page, text); // 立即可见，避免再等 fetch
      setEdits(({ [page]: _drop, ...rest }) => rest);
      setStatus({ ok: true, msg: `已保存 ${stem(page)}.gj；重跑 build_annotations.ts 同步 json/txt` });
    } catch (e) {
      setStatus({ ok: false, msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  const download = () => {
    if (text === undefined || page === undefined) return;
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${stem(page)}.gj`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (error || !index) {
    return (
      <div className="text-muted-foreground flex flex-1 flex-col items-center justify-center gap-2 p-8 text-sm">
        <Database className="size-10 opacity-30" />
        <p>{error ? "数据集访问层读取失败" : "正在读取数据集清单…"}</p>
        {error ? (
          <p className="text-xs">
            先运行 <code className="bg-muted rounded px-1">bash scripts/link-dataset.sh</code>
            （需挂载存放扫描图的外置盘），再刷新页面
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-1.5">
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon-sm" aria-label="上一页" disabled={idx === 0} onClick={() => setIdx(idx - 1)}>
            <ChevronLeft />
          </Button>
          <Button variant="outline" size="icon-sm" aria-label="下一页" disabled={idx === index.length - 1} onClick={() => setIdx(idx + 1)}>
            <ChevronRight />
          </Button>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm">{entry ? `第 ${idx + 1}/${index.length} 页 · @${page}` : "页码"}</Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuLabel>kangxi-gold 页清单</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {index.map((p, i) => (
              <DropdownMenuItem key={p.page} onClick={() => setIdx(i)}>
                @{p.page} · {p.image}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <Separator orientation="vertical" className="h-5" />

        <Button size="sm" variant={flexView ? "ghost" : "default"} onClick={() => setFlexView(false)}>矩阵</Button>
        <Button size="sm" variant={flexView ? "default" : "ghost"} onClick={() => setFlexView(true)}>Flex 对照</Button>
        <Button size="sm" variant="outline" disabled={flexView} aria-pressed={rules} onClick={() => setRules((v) => !v)}>
          界栏{rules ? "开" : "关"}
        </Button>

        <Separator orientation="vertical" className="h-5" />

        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-xs">原图缩放</span>
          <Slider value={[zoom]} onValueChange={([v]) => setZoom(v)} min={30} max={160} step={5} className="w-24" />
          <span className="text-muted-foreground w-10 text-xs tabular-nums">{zoom}%</span>
          {zoom !== 100 ? (
            <Button variant="ghost" size="icon-sm" aria-label="重置缩放" onClick={() => setZoom(100)}>
              <RotateCcw />
            </Button>
          ) : null}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {status ? (
            <span className={`text-xs ${status.ok ? "text-emerald-600" : "text-destructive"}`}>{status.msg}</span>
          ) : null}
          {dirty ? <span className="text-xs text-amber-600">● 未保存</span> : null}
          <Button size="sm" disabled={!dirty || busy} onClick={save}>
            <Save data-icon="inline-start" />
            保存回数据集
          </Button>
          <Button size="sm" variant="outline" disabled={!dirty} onClick={reset}>
            重置
          </Button>
          <Button size="sm" variant="outline" disabled={text === undefined} onClick={download}>
            <Download data-icon="inline-start" />
            下载 .gj
          </Button>
        </div>
      </div>

      <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
        <ResizablePanel defaultSize={38} minSize={20}>
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

        <ResizablePanel defaultSize={34} minSize={20}>
          <div className="flex h-full flex-col">
            <ColumnHeader>
              {flexView ? "Flex" : `矩阵 · ${cols} 列`} · 字格 {unit.toFixed(1)}px · 跟随原图同宽
            </ColumnHeader>
            <ScrollArea className="min-h-0 flex-1">
              <div
                className="flex justify-center p-4"
                style={{ "--guji-scale": `${unit}px` } as CSSProperties}
              >
                {matrixPages.length > 0 ? (
                  flexView ? (
                    <FlexPages pageModels={pageModels} />
                  ) : (
                    <MatrixPages pages={matrixPages} rules={rules} />
                  )
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

        <ResizablePanel defaultSize={28} minSize={20}>
          <div className="flex h-full flex-col">
            <ColumnHeader>
              .gj 编辑器 · @{page} · {dirty ? "未保存" : original !== undefined ? "与数据集一致" : "加载中…"}
            </ColumnHeader>
            <div className="min-h-0 flex-1 overflow-hidden">
              {text !== undefined ? (
                <GujiEditor value={text} onChange={onChange} />
              ) : (
                <div className="text-muted-foreground flex h-full items-center justify-center text-sm">
                  正在加载 {stem(page ?? 0)}.gj…
                </div>
              )}
            </div>
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
