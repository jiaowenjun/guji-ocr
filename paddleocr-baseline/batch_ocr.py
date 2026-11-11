#!/usr/bin/env python3
"""批量 OCR CLI：把目录里的图片提交给本地 paddleocr-baseline 服务并落地结果。

Usage:
  python batch_ocr.py INPUT_DIR [--out OUT_DIR] [--base-url URL] [--concurrency N] [--timeout SECS]

每张图片产出 ``<stem>.md``（OCR markdown）与 ``<stem>.json``（完整结果 JSON）；
失败时产出 ``<stem>.error.txt``。同名 stem 用 image_id 前缀消歧。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


async def run(
    inputs: list[Path],
    out_dir: Path,
    base_url: str,
    concurrency: int,
    timeout_s: float,
    poll_interval_s: float,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        submissions = await _submit_all(client, inputs, semaphore)
        if not submissions:
            print("no images submitted", file=sys.stderr)
            return 1
        failures = await _collect_all(client, submissions, out_dir, semaphore, timeout_s, poll_interval_s)

    succeeded = len(submissions) - failures
    print(f"\n{succeeded}/{len(submissions)} succeeded; results in {out_dir}")
    return 0 if failures == 0 else 1


async def _submit_all(
    client: httpx.AsyncClient,
    inputs: list[Path],
    semaphore: asyncio.Semaphore,
) -> list[tuple[Path, str, str]]:
    async def submit_one(path: Path) -> tuple[Path, str, str] | None:
        async with semaphore:
            response = await client.post(
                "/ocr/images", files={"file": (path.name, path.read_bytes(), _guess_mime(path))}
            )
        if response.status_code != 201:
            print(f"[FAIL] submit {path.name}: HTTP {response.status_code} {response.text[:200]}", file=sys.stderr)
            return None
        image_id = response.json()["image_id"]
        print(f"[UP  ] {path.name} -> {image_id}")
        return path, image_id, response.json()["result_url"]

    results = await asyncio.gather(*(submit_one(path) for path in inputs))
    return [item for item in results if item is not None]


async def _collect_all(
    client: httpx.AsyncClient,
    submissions: list[tuple[Path, str, str]],
    out_dir: Path,
    semaphore: asyncio.Semaphore,
    timeout_s: float,
    poll_interval_s: float,
) -> int:
    async def collect_one(path: Path, image_id: str, result_url: str, stem: str) -> bool:
        """轮询到终态并写文件；返回是否失败。"""
        async with semaphore:
            payload = await _poll_terminal(client, image_id, result_url, timeout_s, poll_interval_s)
        if payload is None:
            (out_dir / f"{stem}.error.txt").write_text(
                f"timeout after {timeout_s}s waiting for {image_id}\n"
            )
            print(f"[FAIL] {path.name}: timeout")
            return True
        if payload.get("error"):
            (out_dir / f"{stem}.error.txt").write_text(payload["error"]["message"] + "\n")
            print(f"[FAIL] {path.name}: {payload['error']['message']}")
            return True
        result = payload.get("result") or {}
        (out_dir / f"{stem}.md").write_text((result.get("markdown") or "") + "\n")
        (out_dir / f"{stem}.json").write_text(
            json.dumps(result.get("json"), ensure_ascii=False, indent=2) + "\n"
        )
        preview = (result.get("text") or "")[:60]
        print(f"[ OK  ] {path.name}: {preview}")
        return False

    stems = _unique_stems(submissions)
    outcomes = await asyncio.gather(
        *(collect_one(path, image_id, url, stems[(path, image_id)]) for path, image_id, url in submissions)
    )
    return sum(1 for failed in outcomes if failed)


def _unique_stems(submissions: list[tuple[Path, str, str]]) -> dict[tuple[Path, str], str]:
    """stem 冲突时附加 image_id 前 8 位十六进制。"""
    stems: dict[tuple[Path, str], str] = {}
    used: set[str] = set()
    for path, image_id, _ in submissions:
        stem = path.stem
        if stem in used:
            stem = f"{path.stem}-{image_id[4:12]}"
        used.add(stem)
        stems[(path, image_id)] = stem
    return stems


async def _poll_terminal(
    client: httpx.AsyncClient,
    image_id: str,
    result_url: str,
    timeout_s: float,
    poll_interval_s: float,
) -> dict | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        response = await client.get(result_url)
        if response.status_code == 200:
            return response.json()
        if response.status_code != 202:
            raise RuntimeError(f"poll {image_id}: HTTP {response.status_code} {response.text[:200]}")
        await asyncio.sleep(poll_interval_s)
    return None


def _guess_mime(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }[path.suffix.lower()]


def main() -> int:
    parser = argparse.ArgumentParser(prog="batch_ocr", description=__doc__)
    parser.add_argument("input", type=Path, help="图片文件或目录")
    parser.add_argument("--out", type=Path, default=Path("out"), help="结果输出目录（默认 ./out）")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010", help="服务地址")
    parser.add_argument("--concurrency", type=int, default=4, help="并发上传/轮询数（默认 4）")
    parser.add_argument("--timeout", type=float, default=600, help="单张图等待终态秒数（默认 600）")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="轮询间隔秒（默认 1.0）")
    args = parser.parse_args()

    if args.input.is_dir():
        inputs = sorted(p for p in args.input.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    elif args.input.is_file():
        inputs = [args.input]
    else:
        parser.error(f"input not found: {args.input}")
    if not inputs:
        parser.error(f"no images under {args.input}")

    return asyncio.run(
        run(inputs, args.out, args.base_url.rstrip("/"), args.concurrency, args.timeout, args.poll_interval)
    )


if __name__ == "__main__":
    sys.exit(main())
