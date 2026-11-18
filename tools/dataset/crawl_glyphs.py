"""Resolve current identity decisions and available local SVGs; never fetch assets."""
from __future__ import annotations
import json
from pathlib import Path
from urllib.parse import quote

import paths


def local_url(root: Path, relative: str, prefix: str) -> str | None:
    path = (root / relative).resolve()
    if path.is_relative_to(root.resolve()) and path.is_file():
        return prefix + quote(path.relative_to(root.resolve()).as_posix(), safe="/")
    return None


def glyph_urls(codepoints: list[int], store) -> dict[str, str]:
    root = paths.UNENCODED_DIR / "kangxi-unencoded"
    mapping: dict[str, str] = {}
    report = root / "report.json"
    if report.is_file():
        for item in json.loads(report.read_text(encoding="utf-8")).get("items", []):
            char, svg = item.get("base_char"), item.get("svg")
            if char and svg:
                mapping.setdefault(char, Path(svg).name)
    patches = root / "font-patches.jsonl"
    if patches.is_file():
        for line in patches.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            for result in record.get("results", []):
                cp, svg = result.get("cp", ""), record.get("svg")
                if cp.startswith("U+") and svg:
                    try:
                        mapping[chr(int(cp[2:], 16))] = Path(svg).name
                    except ValueError:
                        continue
    urls = {}
    for cp in codepoints:
        char = chr(cp)
        if char in mapping:
            url = local_url(root / "svg", mapping[char], "/dataset/unencoded-svg/")
            if url:
                urls[char] = url
    for row in store.glyph_paths(codepoints):
        char = chr(row["codepoint"])
        if char not in urls:
            url = local_url(paths.RAW_KANGXI_SVG, row["svg"], "/dataset/head-svg/")
            if url:
                urls[char] = url
    return urls
