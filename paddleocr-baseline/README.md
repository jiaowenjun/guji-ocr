# paddleocr-baseline

本地 Python 版 PaddleOCR 服务，为古籍 OCR 提供工程基线。架构与对外 API 对齐
weimo `weimo-ocr/backend`（Rust `ocr-app`）：上传图片 → 后台异步提交 PaddleOCR job →
轮询 → 下载并缓存 markdown / JSON / 图片资产；调用方只需上传、轮询结果 URL。

- provider：`https://paddleocr.aistudio-app.com/api/v2/ocr/jobs`，模型 `PaddleOCR-VL-1.6`
- token **必填**，只从 `OCR_TOKEN` 环境变量或 `--token` 参数读取，代码中不内置任何凭据
- 存储与去重：按内容 SHA-256 去重（`img_<sha256>`）；原图 `data/ocr/uploads/ocr-images/`，
  markdown 资产 `data/ocr/uploads/ocr-markdown-assets/<id>/`，元数据 `data/ocr/ocr.sqlite3`（WAL）
- 重试：网络/限流/5xx 按 15/30/60/120/300s 退避，累计 20 次转终态失败；401/403/400 直接终态失败

## 启动

```bash
uv venv --python 3.13 .venv   # 或 python3 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
export OCR_TOKEN="<paddleocr-token>"
.venv/bin/python -m paddleocr_baseline            # 127.0.0.1:8010
.venv/bin/python -m paddleocr_baseline --port 8011 --storage ./data/ocr
```

`OCR_TOKEN` 未设置且未传 `--token` 时启动失败（`OCR token is required`）。

环境变量：`OCR_TOKEN`、`OCR_HOST`、`OCR_PORT`、`OCR_STORAGE_PATH`。

## API

公开端点无鉴权（与 weimo ocr-app 一致），错误统一为 `{"detail": "..."}`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | `{"ok": true, "service": "ocr"}` |
| POST | `/ocr/images` | multipart 字段 `file`（PNG/JPEG/WebP，≤20 MiB）→ 201 + ImageView；同内容去重命中仍 201 |
| GET | `/ocr/images/{id}` | ImageView；`id` 为 `img_` + 64 位 sha256 |
| GET | `/ocr/images/{id}/result` | 处理中 202（result/error 为 null）；终态 200（成功给 `result`，失败给 `error`） |
| GET | `/ocr/images/{id}/source` | 原图字节 |
| GET | `/ocr/images/{id}/assets/{path}` | 缓存的 markdown 图片资产 |

状态机：`pending → running → succeeded | failed`。

```bash
# 上传并轮询
RESP=$(curl -s -F "file=@sample.png" http://127.0.0.1:8010/ocr/images)
ID=$(echo "$RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["image_id"])')
curl -s http://127.0.0.1:8010/ocr/images/$ID/result   # 202 直到 200
```

## 批量 CLI

```bash
.venv/bin/python batch_ocr.py INPUT_DIR --out out --base-url http://127.0.0.1:8010
```

每张图产出 `<stem>.md` 与 `<stem>.json`，失败写 `<stem>.error.txt`；同名 stem 用 image_id 前
8 位消歧。适合对 `datasets/` 下的评测图批量跑基线。

## 测试

```bash
.venv/bin/python -m pytest -q
```

## 与 weimo ocr-app 的差异

- 不实现 admin API（JWT/bcrypt 登录）、Timu 引用扫描；CORS 固定为本地 Vite 端口
- provider job URL / 模型 / optionalPayload 为常量，无 CLI/env 覆盖（与原实现一致）
- 图片嗅探用标准库实现（PNG/JPEG/WebP），不依赖图像库

## 基线记录

2026-11-11 真实链路验证（chronicles-ocr 抽样 3 张）：提交→轮询→下载全通；
`甲骨文/4901e460cb458e6c.jpg`（210×330）成功产出 markdown/json 及 `imgs/img_in_*` 资产缓存；
`隶书/0bdf4bef6f2c296b.png`（164×156 单字）识别为 `☐`——单字古籍样本上 VL 通用模型明显不足，
后续评测记录按 `docs/research/evidence/README.md` 的规范另行建档。
