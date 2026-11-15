# 字体操作留痕登记簿

制度自 2026-11-14 起执行（用户要求：**凡对字体的自定义优化、更新等操作，必须留痕记录**）。本登记簿是人读的汇总台账，与脚本自动追加的机器流水 `var/unencoded/kangxi-unencoded/font-patches.jsonl`（gitignore 内）互为备份——**双轨都要有**：脚本跑完有 jsonl，人做完（或复核完）来本页登记一行。

## 登记规范

**必须登记的操作**（不限于补录）：

| 类别 | 例 |
| --- | --- |
| 字形补录 / 修改 | 向 ttf 注入新字形、改既有字形轮廓 |
| 字体文件替换 | 换版本、重建、重新拆分平面 |
| 缓存戳变更 | index.css `?v=` 递增（无论是否伴随字形变化） |
| 系统字体同步 | `~/Library/Fonts/` 下的同名字体操作（含备份/回滚） |
| 哈希基线漂移排查 | 复核发现字体文件意外变动 |

**每条登记必填字段**：

1. 日期与时间、操作者（脚本名 / 人）；
2. 对象文件的**前后 SHA-256 与字节数**（`shasum -a 256`）；
3. 操作内容与参数（码位、字形源、校准锚等）；
4. 验证手段与数值（chamfer 分、cmap 计数、渲染对比）；
5. 缓存戳（若涉及 index.css）；
6. git 提交哈希（仓库内字体文件变更必须伴随提交，二进制 blob 即历史回滚点）；
7. 回滚点（git blob / 备份文件路径）。

## 登记表

| # | 日期 | 操作 | 对象 | 验证 | 提交 | 详报 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-11-13 19:41 | 补录 U+2BD6E 𫵮（K0000 0334-04，康熙刻形） | guji-large.ttf + 系统字体 | chamfer 0.029（闸 0.15）；cmap 49,407→49,408 双字体一致 | 0ca95d6 | [落地报告](research/2026-11-14-kangxi-guji-large补录U+2BD6E落地报告.md) |
| 2 | 2026-11-14 | （本制度建立 + 首次全量哈希盘点，见下表；修复 PATCH_LOG 路径漂移，未动字体字节） | — | 四字体 + 系统 + 备份六份哈希与预期一致 | 待提交 | 同上报告 §7 |
| 3 | 2026-11-15 | 补录 PUA **U+E701**〈亻人人〉（@349 乑按语，无 Unicode 码位；scheme=scan-trace v1；系统字体有意不同步） | guji-plane0.ttf + guji-large.ttf | chamfer 0.366/0.405（闸 0.5）；cmap 30,706→30,707 / 49,408→49,409，双字体渲染 ✓ | 待提交 | [pua-registry.json](../guji-preview-grid/src/pua-registry.json) + jsonl；工具 tools/dataset/guji_pua_patch.py |

## 哈希基线（2026-11-14 盘点，SHA-256 全量）

- `guji-preview-grid/public/fonts/guji-plane0.ttf`（17,251,716 B，补录后 #3；fontTools 重压缩由 18,386,644 B 缩小）
  `6cdaddc31a13c41bdc602e904fc6d28a6b99422ed62d31651aac7c46345a8f9e`
  （#3 前：`bfd3095240ac6c994e65eec829fe6f269c9609b655fe0904517d6aff19d015e8`，18,386,644 B）
- `guji-preview-grid/public/fonts/guji-large.ttf`（46,624,036 B，补录后 #3）
  `f79d2765b6900a90822971eea286631e93f08f43080d1b8f3e2b8b20af63b9f0`
  （#3 前：`99be6a77b93afa746b2d29e37d6014cab9f9c21471f685a2392426760a17dabf`，46,623,752 B）
- `guji-preview-grid/public/fonts/guji-plane2.ttf`（原始入库，未动）
  `80df094a2e63091b222706696a8b244c9dba45219af866226a097d0fbb2bf28d`
- `guji-preview-grid/public/fonts/guji-planef.ttf`（原始入库，未动）
  `cfeb8527cfc75fe244b1c773056ed8e8896e67918f368999d12f6bd86dee323b`
- `~/Library/Fonts/KX_47043_14.ttf`（46,623,752 B，补录后 #1；与仓库版 3 字节头部校验和区差异，无功能影响）
  `7d916ab6e4bcc935894cd372997ebc7536e315a1e8ae7270d39e53e2dbb9c4fa`
- `~/.kx-font-backup/KX_47043_14-v001014-orig.ttf`（46,698,456 B，**补录前原件**＝git 80cea9a blob，回滚点）
  `dfc5876c1a580922798e5da3f7b58d6bdcf419c294622d67a8a07cf3256da87f`

后续任何登记更新本表；被替换的旧行移入对应报告存档，登记簿只保留最新基线。
