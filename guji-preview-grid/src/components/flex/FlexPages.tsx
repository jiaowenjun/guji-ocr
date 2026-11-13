// Flex 流式渲染（v3 原生）：IR v3 骨架 + overlay 直接渲染，与矩阵视图对照。
// 与已删旧 flex 组件的差异：消费 v3 骨架而非 BlockModel 片段流——小行=物理行
// （换行不进 DOM，.small 的 row-reverse 行序即小行序）；书名不吞换行（v3 契约），
// 书名框按 overlay span 在**整行文本**上切分（先合成行、再按码点切，避免逐元素
// 切分破坏 span 坐标）；边缘按全书阅读序取 book/book-start/middle/end（复用
// flex.css 的去边框拼接）；圆圈按 circle overlay 装饰；不依赖任何 src 偏移。
// 联动与矩阵视图共用 RenderHighlight（book = overlay id）。
import type { CSSProperties, ReactNode } from "react";
import type {
  IRBand,
  IRBookOverlay,
  IRDocument,
  IRElement,
  IRLine,
  IROverlay,
  RenderHighlight,
} from "@/ir/types";
import { GUJI_PROFILE } from "@/ir/types";

const cleanChar = (ch: string) => {
  let out = ch;
  for (const [from, to] of GUJI_PROFILE.normalize) out = out.split(from).join(to);
  return GUJI_PROFILE.stripPunct.includes(out) ? null : out;
};

/** 行内字符片：清洗后文本 + 所属书名 overlay（null=普通段）+ 边缘样式 */
interface Piece {
  text: string;
  overlay: string | null;
  edge: "" | "book" | "book-start" | "book-middle" | "book-end";
}

interface BookIndex {
  byId: Map<string, IRBookOverlay>;
  byLine: Map<string, Array<{ overlayId: string; range: [number, number]; pos: number }>>;
}

/** 构建书名索引：行 → 该行命中的 span（含其在 overlay.spans 中的阅读序位置） */
function bookIndex(doc: IRDocument): BookIndex {
  const byId = new Map<string, IRBookOverlay>();
  const byLine = new Map<string, Array<{ overlayId: string; range: [number, number]; pos: number }>>();
  for (const o of doc.overlays) {
    if (o.kind !== "book-title") continue;
    byId.set(o.id, o);
    o.spans.forEach((span, pos) => {
      const arr = byLine.get(span.line) ?? [];
      arr.push({ overlayId: o.id, range: span.range, pos });
      byLine.set(span.line, arr);
    });
  }
  return { byId, byLine };
}

/** 一个物理行的小字部分 → 字符片序列：先合成整行清洗字（带原文码点偏移），
 *  再按命中的书名 span 切分（span 是原文坐标；边缘按 pos/总 span 数决定） */
function piecesOfLine(
  line: IRLine,
  smallText: string, // 本行全部小字元素拼接（原文，未清洗）
  smallOffset: number, // 小字首字符在整行文本中的原文码点偏移（大字也计入行文本坐标）
  books: BookIndex,
): Piece[] {
  // 合成整行清洗字（原文偏移）
  const chars: Array<{ ch: string; cp: number }> = [];
  let cp = smallOffset;
  for (const ch of smallText) {
    const c = cleanChar(ch);
    if (c !== null) chars.push({ ch: c, cp });
    cp += 1;
  }
  const hits = books.byLine.get(line.id) ?? [];
  const edgeOf = (overlayId: string, pos: number): Piece["edge"] => {
    const total = books.byId.get(overlayId)!.spans.length;
    if (total === 1) return "book";
    return pos === 0 ? "book-start" : pos === total - 1 ? "book-end" : "book-middle";
  };

  const pieces: Piece[] = [];
  let cur: Piece | null = null;
  for (const { ch, cp: cpAt } of chars) {
    const hit = hits.find((h) => cpAt >= h.range[0] && cpAt < h.range[1]);
    const overlayId = hit?.overlayId ?? null;
    if (!cur || cur.overlay !== overlayId) {
      cur = {
        text: ch,
        overlay: overlayId,
        edge: overlayId ? edgeOf(overlayId, hit!.pos) : "",
      };
      pieces.push(cur);
    } else {
      cur.text += ch;
    }
  }
  return pieces;
}

export function FlexPages({
  doc,
  highlight,
  onBandClick,
}: {
  doc: IRDocument;
  highlight?: RenderHighlight;
  onBandClick?: (page: number, index: number) => void;
}) {
  const books = bookIndex(doc);
  const circled = new Set(
    doc.overlays
      .filter((o): o is Extract<IROverlay, { kind: "circle" }> => o.kind === "circle")
      .map((o) => o.target),
  );
  return (
    <div className="pages">
      {doc.pages.map((page, pi) => (
        <div className="page" key={pi}>
          <div className="page-title">{page.no}</div>
          <div className="lines">
            {page.bands.map((band, bi) => (
              <FlexBand
                key={band.id}
                band={band}
                active={highlight?.band?.page === page.no && highlight.band.index === bi}
                books={books}
                circled={circled}
                activeBookId={highlight?.book ?? null}
                onClick={onBandClick ? () => onBandClick(page.no, bi) : undefined}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/** 单个大字格（含合字堆叠与圆圈装饰） */
function LargeCell({ el, circled }: { el: IRElement; circled: boolean }) {
  const stacked = el.ligature && [...el.text].length > 1;
  const inner = stacked ? <span className="stack">{el.text}</span> : el.text;
  return circled ? (
    <div className="large-circle">
      <div className="grid">{inner}</div>
    </div>
  ) : (
    <div className="large">
      <div className="grid">{inner}</div>
    </div>
  );
}

/** 一个小行：字符片 → 逐字格 / 书名框段（均为块级字格，纵向堆叠） */
function SmallLineView({ pieces, activeBookId }: { pieces: Piece[]; activeBookId: string | null }) {
  return (
    <div className="small-line">
      {pieces.map((p, i) =>
        p.overlay ? (
          <div
            key={i}
            className={`book ${p.edge}${p.overlay === activeBookId ? " book-active" : ""}`}
            style={{ display: "flex", flexDirection: "column" } as CSSProperties}
          >
            {[...p.text].map((ch, j) => (
              <div key={j} className="grid">
                {ch}
              </div>
            ))}
          </div>
        ) : (
          [...p.text].map((ch, j) => (
            <div key={`${i}-${j}`} className="grid">
              {ch}
            </div>
          ))
        ),
      )}
    </div>
  );
}

/** 大行：标题 = 顶部缩进 + 大字列；复合 = 段流 [前置小字组] (大字+可选小字组)* */
function FlexBand({
  band,
  active,
  books,
  circled,
  activeBookId,
  onClick,
}: {
  band: IRBand;
  active: boolean;
  books: BookIndex;
  circled: Set<string>;
  activeBookId: string | null;
  onClick?: () => void;
}) {
  const cls = ["line", active && "line-active"].filter(Boolean).join(" ");

  if (band.level !== undefined) {
    const text = band.lines[0]?.elements.map((e) => e.text).join("") ?? "";
    return (
      <div className={cls} onClick={onClick}>
        <div style={{ height: `calc(var(--guji-unit) * 2 * ${band.level - 1})` }} />
        <div className="large">
          <div className="grid">{text}</div>
        </div>
      </div>
    );
  }

  const nodes: ReactNode[] = [];
  let group: Piece[][] = []; // 小字组（小行序）

  const flushGroup = () => {
    if (group.length > 0) {
      nodes.push(
        <div key={`g${nodes.length}`} className="small">
          {group.map((pieces, j) => (
            <SmallLineView key={j} pieces={pieces} activeBookId={activeBookId} />
          ))}
        </div>,
      );
      group = [];
    }
  };

  for (const line of band.lines) {
    // 行内按大字分组：大字把当前「半行」小字切为本组的一个小行，并终结本组
    let smallBuf = ""; // 当前半行的小字原文（未清洗）
    let smallOffset = -1; // 半行首字符在整行文本中的原文码点偏移
    let cp = 0; // 行文本码点游标（大字也推进）
    const flushHalfLine = () => {
      if (smallBuf.length > 0) {
        group.push(piecesOfLine(line, smallBuf, smallOffset, books));
        smallBuf = "";
        smallOffset = -1;
      }
    };
    for (const el of line.elements) {
      if (el.class === "small") {
        if (smallBuf.length === 0) smallOffset = cp;
        smallBuf += el.text;
      } else {
        flushHalfLine();
        flushGroup();
        nodes.push(
          <LargeCell key={`L${nodes.length}`} el={el} circled={circled.has(el.id)} />,
        );
      }
      cp += [...el.text].length;
    }
    flushHalfLine(); // 行边界 = 小行边界（书名不吞换行）
  }
  flushGroup();

  return (
    <div className={cls} onClick={onClick}>
      {nodes}
    </div>
  );
}
