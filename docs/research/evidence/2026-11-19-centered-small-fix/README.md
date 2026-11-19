# 居中小字空格误报修复证据

日期：2026-11-19。对应[修复报告附录 D](../../2026-11-19-427页原图空格识别修复报告.md)。

本次基线为实施 445 页修复之前的工作区，已经包含 427 页修复和 443 页版框恢复，**不是**原报告中更早的 `6bbd4bbe` 基线。前后 API 均只接收页码，网格拟合未改变；区别是检测器新增原图居中小字占位保护。

| 文件 | 用途 |
| --- | --- |
| [manifest.json](manifest.json) | 固定比较范围 312–451，共 140 页；原图目录来自工作区清单 |
| [ocr_scan_before.py](ocr_scan_before.py) | 本轮修复前检测器快照 |
| [ocr_scan_after.py](ocr_scan_after.py) | 本轮修复后检测器快照，验证时与生产文件逐字节一致 |
| [scan_grid_snapshot.py](scan_grid_snapshot.py) | 两版共用、未修改的 API 与网格拟合入口 |
| [replay.py](replay.py) | 调用冻结的新旧完整 API，输出逐页比较 |
| [results.json](results.json) | 全部 140 页的原图哈希、网格、空格、差异、运行时间及源码哈希 |
| [reviewed-deltas.json](reviewed-deltas.json) | 对全部 5 个变化格的原图检查结论 |

```sh
python3 docs/research/evidence/2026-11-19-centered-small-fix/replay.py
```

需要 NumPy、Pillow 和外接原图目录。清单在此冻结，避免用户继续新增页面改变重放范围。140 页中，126 页两版成功定位，14 页两版失败；所有可比较网格完全一致。只有 358、376、445 页的空格集合变化，共移除 5 个居中“古文”旁的假空格，没有新增候选。

358：8→6；376：11→9；445：13→12。427 保持 19 格，其余 123 个成功定位页面集合不变。14 个失败页为 329、337、384–389、392–397；这些页没有空格集合，不能计为“零空格”或正确结果。前一轮发现的纸斑、题字页和印章问题仍保留，不在本轮消除的 5 个误报之内。

[变化格原图](../../figures/2026-11-19-centered-small-fix/corrected-cells.png)中的红框表示本轮移除的误报位置，不代表修复后仍会显示红框。

验证：23 项 Python 扫描测试、10 项前端扫描测试通过；定向 oxlint 和 `git diff --check` 通过。运行中的 `localhost:5173/dataset/scan-grid` 已确认 445 返回 12 格、427 返回 19 格。浏览器缓存版本更新至 `body-grid-v9-centered-small-runs`。没有进行浏览器截图验收，也没有提交或推送。
