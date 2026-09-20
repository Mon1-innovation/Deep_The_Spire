# STS2 录屏关键帧抽取

本组件用于从已有的《杀戮尖塔 2》（STS2）MP4 录屏中自动抽取关键帧，为后续的关键帧识别和战斗日志生成提供图像证据。本组件只负责抽帧和记录来源信息，不负责识别卡牌、遗物、敌人或战斗事件。

## 使用方式

在当前目录下运行：

```powershell
python -m keyframe_extractor `
  --input-dir .\temp\video `
  --output-dir .\segmentation `
  --config .\config\sts2_720p.json
```

批量处理时，程序会扫描 `--input-dir` 下的 MP4 文件。处理单个录屏时，可以使用 `--video path\run_001.mp4`：

```powershell
python -m keyframe_extractor `
  --video .\temp\video\run_001.mp4 `
  --output-dir .\segmentation `
  --config .\config\sts2_720p.json
```

如果输出目录中已经存在相同源文件 SHA-256 且处理成功的 `manifest.json`，程序会自动跳过该视频。使用 `--force` 可以强制重新处理。

## 输出结构

每个录屏对应一个独立的输出目录：

```text
segmentation/
  run_001/
    keyframes/
      kf_000001_t_000012.400.jpg
    keyframes.jsonl
    manifest.json
    warnings.log
```

其中：

- `keyframes/*.jpg`：抽取出的关键帧，保持原始 1280x720 尺寸。
- `keyframes.jsonl`：每行对应一张关键帧，记录帧号、时间戳、触发原因、变化区域、置信度和源文件 SHA-256。
- `manifest.json`：记录输入文件绝对路径、SHA-256、视频尺寸、FPS、帧数、时长、脚本参数、输出数量和处理状态。
- `warnings.log`：记录尺寸或 FPS 不符合预期、解码异常等警告；没有警告时不会生成该文件。

## 默认配置

[config/sts2_720p.json](config/sts2_720p.json) 面向 1280x720、30 FPS 的录屏，包含以下处理参数：

- 每秒粗采样帧数：8，用于降低短暂出牌动作被漏检的概率。
- 普通 ROI 变化阈值、战斗区域变化阈值和问号事件选项变化阈值。
- 稳定帧数量及稳定性阈值。
- 周期锚点间隔。
- pHash 距离和 SSIM 去重阈值。
- 黑屏识别的平均亮度、标准差和暗像素比例阈值。
- STS2 顶部 HUD、战斗中心、手牌区、`combat_hand`、`event_options`、玩家状态区和全屏区域的权重及坐标。

可以复制该 JSON 文件后调整参数，或通过 `--config` 指定自定义配置。ROI 坐标使用 0 到 1 的归一化值，不会裁剪最终保存的关键帧。

其中，`combat_hand` 用于关注战斗中手牌和出牌相关区域，`event_options` 用于关注问号事件的选项面板。两者使用独立的较低变化阈值，即使全屏画面变化不明显，也可以触发候选关键帧。黑屏过滤在锚点和候选帧生成前执行，因此转场黑屏不会被输出。

## 实现边界

实现仅依赖 OpenCV 和 NumPy。程序以单次顺序解码方式处理原视频，通过 ROI 与全屏变化发现候选状态，在画面稳定后保存关键帧，同时定期生成锚点，并使用 pHash/SSIM 去除重复画面。输出的 `frame_index` 和 `keyframes.jsonl` 记录顺序与原视频顺序一致，不需要先切分视频再合并结果。

关键帧的 `trigger` 只表示抽取原因，例如 `roi_change`、`page_change` 或 `periodic_anchor`，不代表已经识别出具体游戏事件。后续的 OCR、视觉模型识别和日志语义推断由 `keyframe_to_log` 负责。

## 处理选项

- `--video` 与 `--input-dir` 互斥；未指定 `--video` 时，程序按路径顺序处理输入目录下的 MP4 文件。
- `--config` 用于指定完整 JSON 配置；`--roi-config` 可单独指定同格式配置文件，当前会覆盖 `--config` 的加载入口。
- `--force` 强制重新处理已有成功 manifest 的视频；否则当源文件 SHA-256 相同且上次处理成功时自动跳过。
- `--dry-run` 仅执行抽帧分析并生成元数据，不写入 JPEG 和 JSONL 关键帧内容。
