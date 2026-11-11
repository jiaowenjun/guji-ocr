"""启动本地 PaddleOCR baseline 服务。

Usage: python -m paddleocr_baseline [--host HOST] [--port PORT] [--storage DIR] [--token TOKEN]
"""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from .config import load_config
from .routes import build_state, create_app


def main() -> int:
    parser = argparse.ArgumentParser(prog="paddleocr_baseline", description=__doc__)
    parser.add_argument("--host", help="监听地址（默认 127.0.0.1，或 OCR_HOST）")
    parser.add_argument("--port", type=int, help="监听端口（默认 8010，或 OCR_PORT）")
    parser.add_argument("--storage", help="原图与结果存储目录（默认 ./data/ocr，或 OCR_STORAGE_PATH）")
    parser.add_argument("--token", help="PaddleOCR token（默认取 OCR_TOKEN 环境变量；无内置值）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = load_config(token=args.token, storage=args.storage, host=args.host, port=args.port)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2
    app = create_app(build_state(config))
    uvicorn.run(app, host=config.bind_host, port=config.bind_port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
