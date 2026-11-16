# 原图定位修订

每页 `NNNN.json` 保存人工确认或修订的扫描图定位。由
`tools/dataset/build_ocr_dataset.py --import-review <下载的 JSON>` 导入。
自动定位结果存于 `var/datasets/kangxi-ocr/`，不自动晋升为人工金标。

文件必须绑定 `source_sha256`（该页 `.gj`）和 `image_sha256`（原图）。
源码／图像改变后，构建器会拒绝旧修订，要求重新核对；不会默默复用序号 ID。

- `band_bboxes`：band ID → `[x1,y1,x2,y2]`，改变大列后重新投影子框。
- `region_bboxes`：region ID → bbox，仅校正该文字片段框，不代表字格也已复核。
- `band_geometry_status`：`proposed` 或 `reviewed`，仅表示大列复核状态。

坐标采用原图像素、左上原点、右／下边界不包含的 xyxy。
原图 `glyphs` 始终是自动投影候选；对其人工终校尚无自动声明途径。
合成图标注由同源布局生成，使用独立坐标，不能抄为原图修订。
