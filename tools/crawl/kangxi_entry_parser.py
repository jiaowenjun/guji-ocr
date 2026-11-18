"""按来源卡片解析康熙字典详情；保留原文、来源身份及附带子段。

纯解析模块，无网络或数据库写入。旧 record 可从已保存 HTML 按需升级。
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import html as html_mod
from html.parser import HTMLParser
import json
import re
import unicodedata
from datetime import date
import urllib.parse

PARSER_VERSION = 2
PARA_SEP = "\ueab1"
DETAIL_TEMPLATE = "https://www.kangxizidian.com/search/index_v.php?stype=Word&sword={sword}&detail=y"


def _plain(text):
    return html_mod.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _field(pattern, source, cast=str):
    match = re.search(pattern, source, re.I | re.S)
    return (cast(_plain(match[1])) if match else None)


def _edition(label, source):
    match = re.search(label + r"</a>：(\d+)頁，第(\d+)字", source)
    return {"page": int(match[1]), "nth_char": int(match[2])} if match else None


def _metadata(source):
    def linked_values(label):
        line = re.search(label + r"：.*?<br\s*/?>", source, re.S | re.I)
        return [_plain(t) for t in re.findall(r">([^<>]+)</a>", line[0])] if line else []
    return {
        "guwen": _field(r"古文：<font24>(.*?)</font24>", source),
        "radical": _field(r"部首：([^<]*)<br", source),
        "radical_strokes": _field(r"部首筆畫：(\d+)", source, int),
        "extra_strokes": _field(r"部外筆畫：(\d+)", source, int),
        "total_strokes": _field(r"總筆畫：(\d+)", source, int),
        "pinyin": linked_values("拼音"), "zhuyin": linked_values("注音"),
        "cangjie": _field(r"倉頡：([^<]*)<br", source),
        "unihan": _field(r"统一碼：([0-9A-Fa-f]+)", source),
        "juan": _field(r"卷別：([^<]*)<br", source),
        "tongwen_edition": _edition("同文書局本", source),
        "wuying_edition": _edition("武英殿本", source),
    }


def _stats(paragraphs):
    return {"text_paragraphs": paragraphs, "text_chars": sum(map(len, paragraphs)),
            "pua_other": sorted({f"U+{ord(c):04X}" for p in paragraphs for c in p
                                  if 0xE000 <= ord(c) <= 0xF8FF and c != PARA_SEP})}


_EDITORIAL = re.compile(r"^(?:（.）)?考證[：:]")


def _normalized(text):
    return "".join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith("P"))


class _BodyText(HTMLParser):
    """保留书名框、BR 段落与 P 子段边界；忽略排版用 ASCII 空格。"""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.spans = []
        self.unsupported = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "span":
            book = "rcornertext" in attrs.get("class", "").split()
            self.spans.append(book)
            if book:
                self.parts.append("【")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "p":
            self.parts.append("\n\x01\n")
        elif tag in ("img", "script", "style"):
            self.unsupported = True

    def handle_endtag(self, tag):
        if tag == "span" and self.spans and self.spans.pop():
            self.parts.append("】")

    def handle_data(self, data):
        self.parts.append(re.sub(r"[\t\r\n \xa0]+", "", data))

    def blocks(self):
        return [[line.strip() for line in block.splitlines() if line.strip()]
                for block in "".join(self.parts).split("\x01") if block.strip()]


def _legacy_detail(source, sword):
    if "字頭：" not in source:
        return None
    og = re.search(r'''og:description["']\s+content=(["'])(.*?)\1''', source, re.S)
    full = html_mod.unescape(og[2]) if og else ""
    paragraphs = [p.strip() for p in full.split(PARA_SEP) if p.strip()]
    if paragraphs and paragraphs[0].startswith(sword + ":"):
        paragraphs[0] = paragraphs[0][len(sword) + 1:]
    return {"sword": sword, "unicode": f"U+{ord(sword):04X}",
            "head": _field(r"字頭：<font color=blue>(.*?)</font>", source),
            **_metadata(source), **_stats(paragraphs), "fetched_at": str(date.today()),
            "source": DETAIL_TEMPLATE.format(sword=urllib.parse.quote(sword))}


def _cards(source):
    # 只认字头缩略图，不按外围重复的 cornerbody div 划分（其中有广告）。
    images = list(re.finditer(
        r"<img\b[^>]*\bsrc\s*=\s*['\"]?(?:\.\./|/)*kxzt/([^\s'\">]+\.svg)['\"]?[^>]*>",
        source, re.I))
    cards = []
    for i, image in enumerate(images):
        fragment = source[image.end():images[i + 1].start() if i + 1 < len(images) else len(source)]
        start = re.search(r"武英殿本</a>：(\d+)頁，第(\d+)字\s*<p>\s*<font20>\s*<font\b[^>]*>", fragment, re.I)
        if not start:
            continue
        end = re.search(r"<p\s+align\s*=\s*['\"]?right\b", fragment[start.end():], re.I)
        identity = re.search(r"(?:^|/)(\d+)-(\d+)-[^/]+-([0-9a-f]+)\.svg$", image[1], re.I)
        if not end or not identity:
            continue
        cp = int(identity[3], 16)
        if cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
            continue
        if int(identity[1]) != int(start[1]) or int(identity[2]) != int(start[2]):
            continue
        body_html = fragment[start.end():start.end() + end.start()]
        parser = _BodyText()
        parser.feed(body_html)
        if parser.unsupported:
            continue
        blocks = []
        for block in parser.blocks():
            split = next((j for j, line in enumerate(block) if _EDITORIAL.match(line)), len(block))
            if split:
                blocks.append(block[:split])
            if split < len(block):
                blocks.append(block[split:])
        cards.append({"head": chr(cp), "unicode": f"U+{cp:04X}", "source_svg": image[1],
                      **_metadata(fragment[:start.end()]), "_blocks": blocks,
                      "source_body_sha256": hashlib.sha256(body_html.encode()).hexdigest()})
    return cards


def _main_blocks(card):
    result = []
    for block in card["_blocks"]:
        # 独立考證栏不属于原来的 og 正文；保留为附带材料，不抄入正文。
        if _EDITORIAL.match("".join(block)):
            break
        result.append(block)
    return result


def _split_attached(cards):
    for card in cards:
        kept, attached, editorial = [], [], False
        for block in card["_blocks"]:
            text = "".join(block)
            editorial = editorial or bool(_EDITORIAL.match(text))
            if editorial:
                attached.append({"kind": "editorial", "text_paragraphs": block})
                continue
            marker = re.match(r"^（(.)）", text)
            target = None
            for other in cards:
                if other is card:
                    continue
                other_text = _normalized("".join(p for b in _main_blocks(other) for p in b))
                if not other_text:
                    continue
                if marker and marker[1] == other["head"]:
                    body = _normalized(text[marker.end():])
                    guwen = _normalized("〔古文〕" + (other.get("guwen") or ""))
                    if body == other_text or (other.get("guwen") and body == guwen + other_text):
                        target = other
                elif (kept and other["head"] == card["head"]
                      and len(other_text) >= 8 and _normalized(text) == other_text):
                    # 无标签重复段必须独占 P 子段，且前面已有本卡正文。
                    target = other
                if target:
                    break
            if target:
                attached.append({"kind": "other_entry", "source_svg": target["source_svg"],
                                 "head": target["head"], "wuying_edition": target["wuying_edition"],
                                 "text_paragraphs": block})
            else:
                kept.extend(block)
        card.update(_stats(kept), attached_segments=attached)


def _original_slice(paragraphs, wanted):
    """HTML 负责归属，能映射回 og 时沿用原标点与段落，避免无关排版改动。"""
    original = "\n".join(paragraphs)
    positions = [i for i, c in enumerate(original) if _normalized(c)]
    normalized = "".join(original[i] for i in positions)
    needle = _normalized("".join(wanted))
    if not needle or needle not in normalized:
        return None
    if needle == normalized:
        return list(paragraphs)
    start = normalized.index(needle)
    end = start + len(needle)
    lo = positions[start]
    line_start = original.rfind("\n", 0, lo) + 1
    if not _normalized(original[line_start:lo]):
        lo = line_start  # 保留段首括注／引号，不仅是书名框。
    else:
        while lo and original[lo - 1] in "【《 \t\n\r　":
            lo -= 1
    hi = positions[end] if end < len(positions) else len(original)
    part = original[lo:hi].rstrip()
    while part and part[-1] in "【《":
        part = part[:-1].rstrip()
    return [p.strip() for p in part.splitlines() if p.strip()]


def select_entry(record, *, head=None, page=None, svg=None):
    """选择唯一来源卡片；不明确时保留原有文本并给出待核原因。"""
    if not record.get("cards"):
        return deepcopy(record)
    head = head or record["sword"]
    candidates = [c for c in record["cards"] if c["head"] == head]
    if svg is not None:
        candidates = [c for c in candidates if c["source_svg"].split("/")[-1] == svg.split("/")[-1]]
    if page is not None:
        candidates = [c for c in candidates if (c.get("wuying_edition") or {}).get("page") == page]
    result = deepcopy(record)
    if len(candidates) == 1 and candidates[0].get("text_origin") == "og_slice":
        result.update(deepcopy(candidates[0]))
        result["selection_status"] = "selected"
        result.pop("selection_note", None)
    else:
        # record 顶层可能已默认选卡；显式页位不匹配不能泄漏默认卡正文。
        for key in ("source_svg", "source_body_sha256", "attached_segments", "text_origin"):
            result.pop(key, None)
        result.update(deepcopy(record["legacy_entry"]))
        result["selection_status"] = "unresolved"
        reason = "正文与原始转写无法完整对应" if len(candidates) == 1 else "来源卡片无法唯一匹配"
        result["selection_note"] = f"字头「{head}」{reason}（页位 {page}），保留原文待核"
    return result


def parse_detail(source, sword):
    legacy = _legacy_detail(source, sword)
    if legacy is None:
        return None
    cards = _cards(source)
    _split_attached(cards)
    for card in cards:
        original = _original_slice(legacy["text_paragraphs"], card["text_paragraphs"])
        if original is not None:
            card.update(_stats(original))
        # 结构归属不等于正文映射正确。少数 HTML 含补遗/异版内容或损坏标签，
        # 未能完整映射回原始转写的卡片留作证据，选择时保守返回旧文。
        card["text_origin"] = "og_slice" if original is not None else "unverified_html"
        del card["_blocks"]
    record = {**legacy, "parser_version": PARSER_VERSION, "cards": cards,
              "legacy_entry": legacy, "selection_status": "legacy"}
    if not cards:
        record["selection_note"] = f"字头「{sword}」来源卡片结构未识别，保留原文待核"
    return select_entry(record)


@lru_cache(maxsize=128)
def _resolve_cached(record_json, raw_html, sword):
    record = json.loads(record_json)
    if record.get("parser_version") == PARSER_VERSION or not raw_html:
        return record
    parsed = parse_detail(raw_html, sword)
    if parsed is None:
        return record
    for key in ("fetched_at", "source", "html_sha256"):
        if key in record:
            parsed[key] = record[key]
    return parsed


def resolve_entry(row, *, head=None, page=None, svg=None):
    record = _resolve_cached(row["record_json"], row.get("raw_html"), row["sword"])
    return select_entry(record, head=head, page=page, svg=svg)
