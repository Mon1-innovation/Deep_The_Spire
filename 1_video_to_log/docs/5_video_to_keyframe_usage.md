# STS2 当前版本抽帧脚本说明

> 对应组件：`1_video_to_log/video_to_keyframe`  
> 当前脚本版本：`0.3.0`  
> 适用配置：`video_to_keyframe/config/sts2_720p.json`  
> 更新日期：2026-09-23

## 1. 作用与边界

抽帧脚本从《杀戮尖塔 2》（STS2）录屏中提取可供后续识别使用的“证据帧”。它关注画面状态变化和来源可追溯性，输出原始尺寸的 JPG、逐帧元数据和处理清单。脚本不负责识别卡牌、遗物、敌人、具体战斗事件或日志语义；这些工作由后续 `keyframe_to_log` 流程完成。

当前实现采用单次顺序解码：先按较低采样率比较 ROI 和全屏变化，发现候选后在原始帧序列中等待画面稳定，再进行周期锚点和 pHash/SSIM 去重。`trigger` 表示抽帧原因，不等同于已经识别出的游戏事件。

## 2. 运行方式

在 `1_video_to_log/video_to_keyframe` 目录执行：

```powershell
python -m keyframe_extractor `
  --input-dir .\temp\video `
  --output-dir .\segmentation `
  --config .\config\sts2_720p.json
```

处理单个视频：

```powershell
python -m keyframe_extractor `
  --video .\temp\video\run_001.mp4 `
  --output-dir .\segmentation `
  --config .\config\sts2_720p.json
```

命令行参数如下：

| 参数                  | 默认值            | 功能                                                     |
| ------------------- | -------------- | ------------------------------------------------------ |
| `--video PATH`      | 无              | 处理一个 MP4；与 `--input-dir` 互斥。                           |
| `--input-dir PATH`  | `temp/video`   | 按路径顺序处理目录下全部 `*.mp4`。                                  |
| `--output-dir PATH` | `segmentation` | 每个视频的输出根目录。                                            |
| `--config PATH`     | 无              | 读取完整 JSON 配置。未指定时使用代码内默认值。                             |
| `--roi-config PATH` | 无              | 读取同格式 JSON；当前实现会加载其中的全部脚本设置，而不只是 ROI。                  |
| `--force`           | 关闭             | 忽略已有成功且 SHA-256 相同的 `manifest.json`，强制重跑。              |
| `--dry-run`         | 关闭             | 执行解码和抽帧分析并写入 manifest，但不写入 JPG 和 `keyframes.jsonl` 内容。 |
| `--debug-video`     | 关闭             | 预留的调试叠加输出开关；当前版本尚未生成调试视频。                              |

无 MP4、输入无法打开或全部视频失败时，程序返回非零退出码；批处理中的单个视频失败不会阻止其余视频继续处理。

## 3. 输入、校验与输出

脚本预期输入为 1280×720、约 30 FPS 的 MP4。尺寸不符或 FPS 不在 29.97–30.03 范围内时会写入警告，但不会自动缩放或停止处理；首帧无法解码则该视频失败。每个视频按文件名建立独立目录：

```text
segmentation/
  run_001/
    keyframes/
      kf_000001_t_000012.400.jpg
    keyframes.jsonl
    manifest.json
    warnings.log        # 只有存在警告时生成
```

- `keyframes/*.jpg`：原始 1280×720 尺寸的关键帧，JPEG 质量由 `jpeg_quality` 控制。
- `keyframes.jsonl`：每行对应一张输出图，包含 `keyframe_id`、`frame_index`、`timestamp_sec`、相对路径、`trigger`、`changed_rois`、`change_score`、`stable_frames`、`dedup_distance`、`confidence` 和输入视频 SHA-256。
- `manifest.json`：记录状态、输入文件、视频宽高/FPS/帧数/时长、脚本版本、实际参数、输出数量和警告数量。写入采用临时文件替换。
- `warnings.log`：记录规格不符、解码/处理异常等信息。单帧异常会跳过；超过 `max_decode_errors` 后视频失败。

若已有 manifest 的 `source.sha256` 与当前文件一致且状态为 `success`，默认跳过处理。`--force` 可覆盖该行为。当前 `dedup_distance` 字段保留在 JSONL schema 中，但写出时为 `null`；pHash/SSIM 仍用于内部判重。

## 4. 抽帧流程与各模块

### 4.1 `cli.py` / `__main__.py`

`__main__.py` 将模块调用转给 `cli.main()`。`cli.py` 负责解析命令行、载入设置、枚举视频、逐个调用 `pipeline.extract_video()` 并汇总退出码。`--debug-video` 当前只被解析，不改变抽帧行为。

### 4.2 `config.py`

定义 `Roi` 和 `Settings` 数据结构。ROI 使用 0–1 归一化坐标，`Roi.pixels()` 将其映射为像素矩形并裁剪到画面边界。`load_settings()` 从 JSON 覆盖同名设置；未提供的字段保留代码默认值。

### 4.3 `video.py`

计算输入 SHA-256，打开 OpenCV 视频，读取宽高/FPS/总帧数/时长，验证首帧可解码，并按原始顺序产生 `(frame_index, timestamp_sec, frame)`。时间戳按 `frame_index / fps` 计算，帧序号从 0 开始。

### 4.4 `scores.py`

- `small_gray()`：将帧转灰度并缩放到 320×180，用于低成本比较。
- `is_black_frame()`：依据平均亮度、标准差和暗像素比例过滤转场黑屏。
- `roi_scores()`：对每个 ROI 计算灰度平均绝对差（MAD），按 ROI 权重合并局部变化分数，同时计算全屏低分辨率变化分数，并返回发生变化的 ROI 名称。
- `phash()` / `phash_distance()`：生成 64 位 DCT 感知哈希并计算汉明距离。
- `ssim()`：在 320×180 灰度图上计算结构相似度，作为 pHash 判重的复核。

### 4.5 `selector.py`

`Selector.consider()` 完成黑屏过滤、粗采样、OCR 检查、ROI/全屏阈值判断、候选窗口、稳定帧确认、周期锚点和去重。变化达到阈值后先建立 pending 候选；连续 `stable_frames` 个比较帧的变化低于 `stable_threshold` 时输出最佳稳定帧，超过 `settle_timeout` 仍未稳定则输出窗口内最佳帧并将置信度设为 `low`。文件结束时由 `finish()` 刷新尚未完成的候选。

### 4.6 `ocr.py`

`battle_start_text()` 是可选的战斗开始提示 OCR。只有 `battle_start_ocr.enabled=true` 且环境安装 `pytesseract` 时才会运行；它在固定的 `(x=0.20,y=0.20,w=0.60,h=0.35)` 区域识别文字，并匹配配置关键词。命中时触发 `combat_start_ocr`。

### 4.7 `output.py` / `pipeline.py`

`output.py` 提供 JPEG 编码和原子 JSON 写入。`pipeline.py` 负责单视频生命周期、断点安全输出、警告收集、manifest 生成和资源释放。ROI 只用于分析，最终 JPG 不裁剪。

## 5. 当前 ROI

坐标均为相对于 1280×720 画面的归一化值；`weight` 用于局部变化的加权合并。ROI 可以重叠，`full_frame` 覆盖整幅画面。

| 名称                   | x    | y    | w    | h    | weight | 关注内容                           |
| -------------------- | ----:| ----:| ----:| ----:| ------:| ------------------------------ |
| `top_hud`            | 0.00 | 0.00 | 0.42 | 0.18 | 0.7    | 左上 HUD、生命/金币/层数等。              |
| `combat_center`      | 0.20 | 0.18 | 0.60 | 0.58 | 1.5    | 敌人、意图和战斗中心区域。                  |
| `hand`               | 0.12 | 0.72 | 0.76 | 0.28 | 1.5    | 底部手牌区域。                        |
| `combat_hand`        | 0.18 | 0.64 | 0.64 | 0.30 | 2.2    | 战斗中手牌和出牌区域，敏感度更高。              |
| `selection_overlay`  | 0.28 | 0.16 | 0.44 | 0.58 | 2.0    | 中央放大选牌确认区域。                    |
| `deck_overlay`       | 0.10 | 0.08 | 0.80 | 0.84 | 1.8    | 牌堆平铺和牌组查看区域。                   |
| `potion_bar`         | 0.78 | 0.56 | 0.22 | 0.30 | 1.6    | 独立药水栏位。                        |
| `event_options`      | 0.18 | 0.24 | 0.64 | 0.54 | 2.4    | 事件选项面板。                        |
| `shop_decision`      | 0.10 | 0.16 | 0.80 | 0.70 | 1.8    | 商店决策区域。                        |
| `player_status_left` | 0.18 | 0.62 | 0.20 | 0.16 | 2.6    | 左侧角色生命、格挡和状态图标；出牌后状态变化的敏感区域。   |
| `player_energy_left` | 0.00 | 0.74 | 0.14 | 0.16 | 2.2    | 左下能量区域，避开大部分手牌展开区域。            |
| `player_status`      | 0.68 | 0.00 | 0.32 | 0.28 | 1.2    | 右上角运行元数据（种子号、游戏版本及该区域 HUD 文本）。 |
| `full_frame`         | 0.00 | 0.00 | 1.00 | 1.00 | 0.9    | 地图、商店、事件及全屏页面变化。               |

`combat_center`、`combat_hand`、`event_options` 和 `shop_decision` 使用各自更低的变化阈值，以减少短暂出牌、事件选项和商店操作的漏检。ROI 名称只描述证据区域，不表示脚本已经完成场景分类。

`player_status` 是历史兼容名称。当前录像中该区域主要显示种子号、游戏版本号等运行元数据，并不应解释为稳定的玩家状态、能量和图标识别区域。它仍作为普通 ROI 参与局部帧差计算，因此暂不删除或改名：删除会改变 ROI 权重归一化以及候选帧的触发/稳定判定，改名还会破坏已有配置和 `changed_rois` 消费方。若后续需要更准确的语义名称，建议新增配置版本并提供 `player_status` 到新名称的兼容别名，待下游迁移后再废弃旧名称。

`player_status_left` 与 `player_energy_left` 使用较高权重和专用低阈值，属于战斗敏感 ROI，会参与出牌相关候选帧判断和伪关键帧回退。两个区域刻意避开大块左下手牌区，以减少手牌动画干扰。

## 6. 配置参数

以下为当前 `sts2_720p.json` 的有效配置项。数值阈值使用归一化灰度差（0–1）或代码注明的单位。

| 参数                              | 当前配置                  | 功能                                                 |
| ------------------------------- | ---------------------:| -------------------------------------------------- |
| `coarse_fps`                    | 16                    | 粗扫比较频率（帧/秒）；越高越不易漏掉短变化，但计算量更大。                     |
| `change_threshold`              | 0.08                  | 通用 ROI 加权局部变化阈值。                                   |
| `page_threshold`                | 0.18                  | 全屏变化阈值，触发 `page_change` 候选。                        |
| `roi_change_threshold`          | 0.025                 | 普通 ROI 单区变化阈值。                                     |
| `combat_change_threshold`       | 0.018                 | `combat_center`、`combat_hand` 阈值。                  |
| `event_change_threshold`        | 0.018                 | `event_options` 阈值。                                |
| `shop_change_threshold`         | 0.018                 | `shop_decision` 阈值。                                |
| `player_status_change_threshold` | 0.015                | `player_status_left`、`player_energy_left` 专用阈值。    |
| `stable_frames`                 | 3                     | 连续满足稳定条件所需的比较帧数。                                   |
| `stable_threshold`              | 0.025                 | 候选帧之间被视为稳定的变化上限。                                   |
| `anchor_interval`               | 5                     | 周期锚点间隔（秒）；用于覆盖长时间静止页面。                             |
| `phash_distance`                | 6                     | pHash 汉明距离不超过该值时进入 SSIM 去重判断。                      |
| `ssim_threshold`                | 0.985                 | SSIM 大于等于该值视为重复帧。                                  |
| `pre_roll`                      | 0.5                   | 配置中保留的候选前置时间（秒）；当前 selector 尚未使用该值。                |
| `settle_timeout`                | 2                     | 候选等待稳定的最长时间（秒）。                                    |
| `black_mean_threshold`          | 8                     | 黑屏平均灰度阈值。                                          |
| `black_std_threshold`           | 12                    | 黑屏灰度标准差阈值。                                         |
| `black_dark_ratio`              | 0.995                 | 暗像素比例阈值。                                           |
| `jpeg_quality`                  | 95                    | JPG 编码质量。                                          |
| `max_decode_errors`             | 10                    | 单视频允许的累计解码/处理异常数。                                  |
| `pseudo_keyframe_fallback`      | `true`                | 是否在敏感 ROI 变化时回退到变化前的粗采样帧；仓库 `sts2_720p.json` 默认开启。 |
| `pseudo_keyframe_rois`          | `combat_hand`, `hand` | 触发回退的 ROI 名称；回退帧的 trigger 增加 `_pre_coarse`。        |
| `pseudo_keyframe_scope`         | `global`              | 伪关键帧适用范围：`combat`、`decision` 或 `global`。           |
| `decision_merge_rois`           | `event_options`, `shop_decision`, `deck_overlay` | 决策界面合并和 `decision` 作用域回退使用的 ROI。 |
| `decision_merge_window`         | 1.5                   | 决策界面近帧合并时间窗口（秒）。                                   |
| `decision_merge_ssim`           | 0.94                  | 决策界面合并使用的 SSIM 下限。                                 |
| `decision_merge_phash_distance` | 12                    | 决策界面合并使用的 pHash 距离上限。                              |
| `battle_start_ocr.enabled`      | `false`               | 是否启用战斗开始 OCR（默认关闭；不建议常规启用）。                        |
| `battle_start_ocr.interval`     | 1.0                   | 两次 OCR 尝试的最短间隔（秒）。                                 |
| `battle_start_ocr.keywords`     | 配置列表                  | OCR 文本命中任一关键词时触发战斗开始帧。                             |
| `rois`                          | 见上表                   | 完整 ROI 列表；可通过 JSON 覆盖。                             |

不提供配置文件时，代码默认 `coarse_fps=6`、`stable_frames=5`、`pseudo_keyframe_scope=combat`；使用仓库配置文件时分别为 `16`、`3` 和 `global`。`pre_roll` 已被解析并写入设置接口，但当前版本没有根据它回溯输出帧；如需改变行为，应先修改 selector 并补充测试。使用仓库 `sts2_720p.json` 时 `pseudo_keyframe_fallback` 默认开启，OCR 默认关闭；自定义配置可关闭伪关键帧回退，不影响普通抽帧路径。

## 7. trigger、置信度与去重语义

可能出现的 `trigger` 包括：

- `periodic_anchor`：首帧或达到锚点间隔时的覆盖性输出；
- `roi_change`：局部 ROI 变化达到阈值；
- `page_change`：全屏变化达到页面阈值；
- `combat_start_ocr`：可选 OCR 命中战斗开始提示；
- `roi_change_pre_coarse` / `page_change_pre_coarse`：启用伪关键帧回退后使用变化前粗采样帧。

`confidence=candidate` 表示在稳定帧条件下确认，`confidence=low` 表示达到超时或视频结束时仍未完成稳定确认。pHash 距离过小且 SSIM 达到阈值时，候选会被丢弃，以避免重复 JPG；该丢弃不会改变原始视频帧序列。

## 8. 与后续日志流程的接口

后续流程应读取 `keyframes.jsonl` 中的相对路径、`frame_index`、`timestamp_sec`、`trigger`、`changed_rois` 和 `confidence`，并保留输入视频及 SHA-256 关联。抽帧脚本只提供图像证据和 provenance；不得根据 `trigger` 直接推断卡牌、事件或动作语义。

## 9. 高密度动作采样与伪关键帧作用域

仓库提供的 `sts2_720p.json` 使用 `coarse_fps=16` 和 `stable_frames=3`。提高粗采样频率可以降低短暂出牌或选牌变化落在采样间隔之间、从而被遗漏的概率；减少稳定确认帧数可以缩短确认延迟。pHash/SSIM 去重仍会抑制视觉上重复的输出。

`pseudo_keyframe_scope` 会在启动时从配置文件读取：

- `combat`：仅对手牌和战斗相关变化启用回退。
- `decision`：对 `decision_merge_rois` 中列出的决策界面 ROI 启用回退。
- `global`：任何通过变化检测的候选帧都可以回退到前一个粗采样帧。

实际生效的作用域和合并参数会写入 `manifest.json`。当输入视频 SHA-256 未变化且已有成功 manifest 时，脚本会跳过处理；修改配置或脚本行为后应使用 `--force` 重新运行。
