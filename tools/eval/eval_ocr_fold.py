#!/usr/bin/env python3
"""初校真值 × OCR 行组 对照评估：折行组界质量（真行界率/过分裂/漏折）。

用法：python3 tools/eval/eval_ocr_fold.py [-v]
  -v 打印每个过分裂数的上下文（组文本、金标对齐位置）。
数据源：kangxi-gold/annotations/*.gj（初校真值）+ var/ocr-cache/*.json。
口径与 tools/dataset/kangxi_page_tool.py 的 _norm/PUNCT_STRIP 一致。
2026-11-14 全量基线见 docs/research/evidence/2026-11-14-ocr-bbox-fold-feasibility.json。
"""
import difflib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths  # noqa: E402

GJ = REPO / "kangxi-gold/annotations"
OCR_CACHE = paths.OCR_CACHE_DIR
PUNCT_STRIP = "。，·\"：:、；《》【】*　 \t\n\r"


def norm(text: str) -> str:
    return "".join(ch for ch in text if ch not in PUNCT_STRIP)


def gj_bands(path: Path) -> list:
    """解析 .gj：@页码 行之后，空行分组=带，带内每行=物理行（跳过 # 注释）。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        at = next(i for i, l in enumerate(lines) if l.startswith("@"))
    except StopIteration:
        raise ValueError(f"no @page line in {path}")
    body = "\n".join(lines[at + 1:])
    bands = []
    for chunk in body.split("\n\n"):
        ls = [l for l in chunk.split("\n") if l.strip() and not l.strip().startswith("#")]
        if ls:
            bands.append(ls)
    return bands


def evaluate(page: int, verbose_failures: bool = False):
    gj = GJ / f"{page:04d}.gj"
    cache = OCR_CACHE / f"{page:04d}.json"
    if not gj.exists() or not cache.exists():
        return None
    bands = gj_bands(gj)
    gold_lines = [l for b in bands for l in b]
    gold_n = norm("".join(gold_lines))
    true_bounds, acc = set(), 0
    for l in gold_lines:
        acc += len(norm(l))
        true_bounds.add(acc)
    true_bounds.discard(len(gold_n))

    md = json.loads(cache.read_text(encoding="utf-8"))["markdown"]
    groups = [g.replace("\n", "") for g in md.split("\n\n") if g.strip()]
    ocr_n = norm("".join(groups))

    sm = difflib.SequenceMatcher(None, gold_n, ocr_n, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    cover = sum(b.size for b in blocks)
    aligned = cover >= len(ocr_n) * 0.5 and cover >= len(gold_n) * 0.5

    ocr_off, acc2 = [], 0
    for g in groups[:-1]:
        acc2 += len(norm(g))
        ocr_off.append(acc2)
    mapped = []
    for o in ocr_off:
        for b in blocks:
            if b.b <= o <= b.b + b.size:
                mapped.append(b.a + (o - b.b))
                break
        else:
            mapped.append(None)

    exact = sum(1 for p in mapped if p in true_bounds)
    near = sum(1 for p in mapped if p is not None and p not in true_bounds
               and any(abs(p - t) <= 2 for t in true_bounds))
    bad = [p for p in mapped if p is not None and p not in true_bounds
           and not any(abs(p - t) <= 2 for t in true_bounds)]
    unmapped = sum(1 for p in mapped if p is None)
    hit_set = {p for p in mapped if p is not None and any(abs(p - t) <= 2 for t in true_bounds)}
    missed = len(true_bounds - hit_set)

    result = dict(page=page, gold_lines=len(gold_lines), ocr_groups=len(groups),
                  bounds=len(mapped), exact=exact, near=near, bad=len(bad),
                  unmapped=unmapped, missed_bounds=missed, cover=cover,
                  len_gold=len(gold_n), len_ocr=len(ocr_n), aligned=aligned)
    if verbose_failures:
        result["bad_ctx"] = []
        for i, p in enumerate(mapped):
            if p in bad:
                dist = min((abs(p - t) for t in true_bounds), default=999)
                result["bad_ctx"].append(dict(
                    group=i, gold_pos=p, dist_nearest_true=dist,
                    ocr_group_len=len(norm(groups[i])),
                    ocr_group_text=groups[i][:30],
                    gold_around=gold_n[max(0, p - 12):p + 12],
                ))
    return result


if __name__ == "__main__":
    verbose = "-v" in sys.argv
    pages = sorted(int(f.stem) for f in OCR_CACHE.glob("[0-9]*.json"))
    rows = [r for r in (evaluate(p, verbose) for p in pages) if r]
    tot = dict(gold_lines=0, ocr_groups=0, bounds=0, exact=0, near=0, bad=0,
               unmapped=0, missed_bounds=0)
    for r in rows:
        for k in tot:
            tot[k] += r[k]
        flag = "" if r["aligned"] else "  <对齐不可信>"
        print(f"@{r['page']}: gold行={r['gold_lines']} ocr组={r['ocr_groups']} "
              f"组界={r['bounds']} 精确={r['exact']} ±2={r['near']} 过分裂={r['bad']} "
              f"未映射={r['unmapped']} 漏折={r['missed_bounds']}{flag}")
        if verbose:
            for c in r.get("bad_ctx", []):
                print(f"    ✗ @{r['page']} 组{c['group']} len={c['ocr_group_len']} "
                      f"gold_pos={c['gold_pos']} 距真界{c['dist_nearest_true']} "
                      f"ocr='{c['ocr_group_text']}' gold↔'{c['gold_around']}'")
    n = len(rows)
    mappable = tot["bounds"] - tot["unmapped"]
    hit = tot["exact"] + tot["near"]
    print(f"\n== {n} 页合计 ==")
    print(f"gold 物理行 {tot['gold_lines']}，OCR 组 {tot['ocr_groups']}")
    print(f"组界 {tot['bounds']}（可映射 {mappable}）：真行界 {hit}"
          f"（{(hit / mappable * 100 if mappable else 0):.1f}%），过分裂 {tot['bad']}")
    print(f"漏折 {tot['missed_bounds']}/{tot['gold_lines']}")
