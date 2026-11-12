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
import { ChevronLeft, ChevronRight, Database, Download, Plus, RotateCcw, Save } from "lucide-react";
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
  status?: "draft" | "first" | "final"; // 草稿 / 初校 / 精校（存于 manifest.json）
}

/** 页标签：内部值 ↔ 中文名与展示色 */
const STATUS_META: Record<PageEntry["status"] & string, { label: string; dot: string; text: string }> = {
  draft: { label: "草稿", dot: "bg-muted-foreground", text: "text-muted-foreground" },
  first: { label: "初校", dot: "bg-amber-500", text: "text-amber-600" },
  final: { label: "精校", dot: "bg-emerald-500", text: "text-emerald-600" },
};

const stem = (page: number) => String(page).padStart(4, "0");

/** 武英殿版扫描的版框（印刷内容框）到纸边距离，自然像素、页宽 1130。
 *  17 页投影法实测中位数（列/行暗像素计数定位贯穿框线，左侧书脊暗带与
 *  底部水印区已排除）；扫描同源，取常量即可，渲染列据此做等比纸边。 */
const SCAN_FRAME_MARGIN = { left: 124, right: 104, top: 150, bottom: 97 };
/** 扫描纸面色（0312 纸边取样平均） */
const PAPER_BG = "#dcb68a";

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

/** 页清单（public/dataset/index.json） */
function useDatasetIndex() {
  const [index, setIndex] = useState<PageEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
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
  }, [reloadKey]);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);
  return { index, error, reload };
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
    <div className="text-muted-foreground bg-background/60 border-b px-3 py-1 text-xs">
      {children}
    </div>
  );
}

export function DatasetView({ editorTheme = "light" }: { editorTheme?: "light" | "dark" }) {
  const { index, error, reload } = useDatasetIndex();
  const [idx, setIdx] = useState(0);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const { texts, ensure, put } = useDatasetText();
  const [rules, setRules] = useState(false); // 界栏默认关（默认 Flex 视图下也不可用）
  const [flexView, setFlexView] = useState(true); // 默认 Flex 布局
  const [zoom, setZoom] = useState<number | "fit">("fit"); // 默认按原图高度适配视口
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [adding, setAdding] = useState(false); // 添加新页表单开合
  const [pageInput, setPageInput] = useState("");
  const [addBusy, setAddBusy] = useState(false); // 添加新页进行中
  const [jumpTo, setJumpTo] = useState<number | null>(null); // 添加成功后跳转

  // 清单刷新后跳到新添加的页
  useEffect(() => {
    if (index && jumpTo !== null) {
      const i = index.findIndex((p) => p.page === jumpTo);
      if (i >= 0) {
        setIdx(i);
        setJumpTo(null);
      }
    }
  }, [index, jumpTo]);

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
  // 渲染 unit 对齐版框内容宽（而非整图宽），矩阵视图下渲染页宽 = frameWidth

  // 原图列内容宽高 → 显示宽 → 渲染 unit（同宽联动）
  const { ref: scanRef, width: scanWidth, height: scanHeight } = useContentSize<HTMLDivElement>();
  const fitHeight = zoom === "fit";
  const displayWidth = fitHeight
    ? entry && scanHeight > 0
      ? Math.floor((scanHeight * entry.width) / entry.height) // 向下取整，避免 1px 溢出触发滚动条
      : Math.max(200, scanWidth)
    : Math.max(200, Math.round((scanWidth * zoom) / 100));
  // 等比纸边：渲染列包一层与扫描同尺寸的"纸"，内容区对齐版框
  const scanScale = entry ? displayWidth / entry.width : 0;
  const paperPad = {
    left: SCAN_FRAME_MARGIN.left * scanScale,
    right: SCAN_FRAME_MARGIN.right * scanScale,
    top: SCAN_FRAME_MARGIN.top * scanScale,
    bottom: SCAN_FRAME_MARGIN.bottom * scanScale,
  };
  const frameWidth = displayWidth - paperPad.left - paperPad.right;

  // 纸层高度与扫描显示高一致（网格行数 × 宽度字格 ≠ 版框实际高，会矮一截，
  // 在深色主题下表现为纸层上下的黑边）：显式 minHeight = 图片等比高，
  // 纵向富余按版框实测上/下边距比例分配（左右边距不变，纸宽本就相等）
  const { ref: paperContentRef, height: paperContentH } = useContentSize<HTMLDivElement>();
  const paperHeight = entry ? Math.floor((displayWidth * entry.height) / entry.width) : 0;
  const verticalBudget = paperHeight - paperContentH;
  const marginSum = SCAN_FRAME_MARGIN.top + SCAN_FRAME_MARGIN.bottom;
  const paperPadY =
    verticalBudget > paperPad.top + paperPad.bottom && paperContentH > 0
      ? {
          top: (verticalBudget * SCAN_FRAME_MARGIN.top) / marginSum,
          bottom: (verticalBudget * SCAN_FRAME_MARGIN.bottom) / marginSum,
        }
      : { top: paperPad.top, bottom: paperPad.bottom };
  const unit = cols > 0 ? (frameWidth - 2) / cols : 25;

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

  /** 添加新页：桥接 kangxi_page_tool.py（sqlite 优先，缺则增量爬取），完成后刷新清单并跳转 */
  const addPage = async () => {
    const n = Number(pageInput);
    if (!/^\d{1,4}$/.test(pageInput) || n < 1 || n > 7738) {
      setStatus({ ok: false, msg: `页码应为 1-7738 的整数（当前输入：${pageInput || "空"}）` });
      return;
    }
    setAddBusy(true);
    setStatus(null);
    try {
      const res = await fetch("/dataset/page-tool", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action: "add", page: n }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        ok?: boolean;
        error?: string;
        counts?: { chars: number; unencoded: number; with_text: number };
        summaries?: string[];
      };
      if (!res.ok || !data.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      const { counts, summaries } = data;
      reload();
      setJumpTo(n);
      setAdding(false);
      setPageInput("");
      setStatus({
        ok: true,
        msg: `已添加 @${n}（字头 ${counts?.chars ?? "?"} 个，含释义 ${counts?.with_text ?? "?"}，未编码 ${counts?.unencoded ?? 0}）${summaries?.length ? "；" + summaries.join("；") : ""}`,
      });
    } catch (e) {
      setStatus({ ok: false, msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setAddBusy(false);
    }
  };

  /** 改页标签（kangxi_page_tool.py 写 manifest + index.json），成功后刷新清单 */
  const setStatusOf = async (to: NonNullable<PageEntry["status"]>) => {
    if (page === undefined) return;
    try {
      const res = await fetch("/dataset/page-tool", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action: "status", page, status: to }),
      });
      const data = (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string };
      if (!res.ok || !data.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      reload();
      setStatus({ ok: true, msg: `@${page} 标签已改为「${STATUS_META[to].label}」` });
    } catch (e) {
      setStatus({ ok: false, msg: e instanceof Error ? e.message : String(e) });
    }
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
                      <span
                        className={`inline-block size-1.5 shrink-0 rounded-full ${STATUS_META[p.status ?? "first"].dot}`}
                      />
                      @{p.page} · {STATUS_META[p.status ?? "first"].label} · {p.image}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" disabled={!entry}>
                    <span
                      className={`inline-block size-2 rounded-full ${STATUS_META[entry?.status ?? "first"].dot}`}
                    />
                    {STATUS_META[entry?.status ?? "first"].label}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuLabel>页标签（存 manifest.json）</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {(Object.keys(STATUS_META) as NonNullable<PageEntry["status"]>[]).map((s) => (
                    <DropdownMenuItem key={s} onClick={() => setStatusOf(s)}>
                      <span className={`inline-block size-1.5 rounded-full ${STATUS_META[s].dot}`} />
                      {STATUS_META[s].label}
                      {entry?.status === s ? " ✓" : ""}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>

              {adding ? (
                <div className="flex items-center gap-1">
                  <input
                    value={pageInput}
                    onChange={(e) => setPageInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") addPage();
                    }}
                    disabled={addBusy}
                    placeholder="页码 1-7738"
                    inputMode="numeric"
                    className="border-input bg-background h-7 w-24 rounded-md border px-2 text-xs outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  />
                  <Button size="sm" onClick={addPage} disabled={addBusy}>
                    确认添加
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setAdding(false)} disabled={addBusy}>
                    取消
                  </Button>
                </div>
              ) : (
                <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
                  <Plus data-icon="inline-start" />
                  添加新页
                </Button>
              )}


        <Separator orientation="vertical" className="h-5" />

        <Button size="sm" variant={flexView ? "ghost" : "default"} onClick={() => setFlexView(false)}>矩阵</Button>
        <Button size="sm" variant={flexView ? "default" : "ghost"} onClick={() => setFlexView(true)}>Flex 对照</Button>
        <Button size="sm" variant="outline" disabled={flexView} aria-pressed={rules} onClick={() => setRules((v) => !v)}>
          界栏{rules ? "开" : "关"}
        </Button>

        <Separator orientation="vertical" className="h-5" />

        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-xs">原图缩放</span>
          <Slider
            value={[fitHeight ? 100 : zoom]}
            onValueChange={([v]) => setZoom(v)}
            min={30}
            max={160}
            step={5}
            className="w-24"
          />
          <span className="text-muted-foreground w-12 text-xs">
            {fitHeight ? "高度适配" : `${zoom}%`}
          </span>
          {!fitHeight ? (
            <Button variant="ghost" size="icon-sm" aria-label="恢复高度适配" onClick={() => setZoom("fit")}>
              <RotateCcw />
            </Button>
          ) : null}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {addBusy ? (
            <span className="text-amber-600 text-xs">
              抓取新页中…（sqlite 已有数据不联网，缺则增量爬取，约 10-60s）
            </span>
          ) : null}
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
              {flexView ? "Flex" : `矩阵 · ${cols} 列`} · 字格 {unit.toFixed(1)}px ·{" "}
              {flexView ? "版框近似对齐（行宽按内容混合，精确对照请用矩阵）" : "与原图版框对齐（含等比纸边）"}
            </ColumnHeader>
            <ScrollArea className="min-h-0 flex-1">
              <div className="flex justify-center p-2">
                {matrixPages.length > 0 ? (
                  <div
                    className="relative shrink-0"
                    style={{
                      width: displayWidth,
                      minHeight: paperHeight,
                      paddingTop: paperPadY.top,
                      paddingRight: paperPad.right,
                      paddingBottom: paperPadY.bottom,
                      paddingLeft: paperPad.left,
                      background: PAPER_BG,
                    }}
                  >
                    <div
                      ref={paperContentRef}
                      className="flex justify-center"
                      style={{ "--guji-scale": `${unit}px` } as CSSProperties}
                    >
                      {flexView ? (
                        <FlexPages pageModels={pageModels} />
                      ) : (
                        <MatrixPages pages={matrixPages} rules={rules} />
                      )}
                    </div>
                  </div>
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
              .gj 编辑器 · @{page} · {dirty ? "未保存" : original !== undefined ? "与数据集一致" : "加载中…"}
            </ColumnHeader>
            <div className="min-h-0 flex-1 overflow-hidden">
              {text !== undefined ? (
                <GujiEditor value={text} onChange={onChange} theme={editorTheme} />
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
