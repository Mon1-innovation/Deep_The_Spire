# STS2 录屏关键帧抽取脚本方案

> 日期：2026-09-19  
> 范围：从 720P/30FPS/mp4 的 STS2 录屏生成供 `keyframe_to_log` 使用的 JPG 关键帧。  
> 依据：`docs/0_research_sts_video_to_combat_log.md`、`docs/1_work_initiation.md`。

## 1. 方案定位

脚本的目标不是做普通镜头切换检测，而是保留能够表达“玩家操作前后状态”的画面：例如回合开始、手牌变化、敌人意图变化、奖励选项展开和页面切换。

STS2 大部分时间保持同一 UI 画面，整帧场景检测会漏掉这些局部变化。因此采用本地 CPU、无 API 的两级流程：

1. 用固定采样率扫描视频，在预定义 ROI 上计算变化分数，发现候选状态变化。
2. 在候选变化之后逐帧等待画面稳定，保存第一张稳定帧；用 pHash/SSIM 去除重复帧。

通用场景检测（PySceneDetect 或 ffmpeg `scene` filter）只作为可选的镜头切换兜底，不能决定主要关键帧。M1 应先用同步真值录像测量召回率，再冻结阈值；不要在没有真值的情况下宣称抽帧准确。

现有里程碑中，M1 的正式产物是 20--50 局同步录像与真值日志，关键帧抽取引擎属于后续 M2。本文沿用用户所说的“M1 采用方案”，但脚本必须保留真值评测接口，方便 M1 校验集直接评估。

## 2. 目录和输入输出合同

路径均以仓库根目录为基准，脚本同时接受命令行覆盖：

```text
输入：1_video_to_log/video_to_keyframe/temp/video/*.mp4
输出：1_video_to_log/video_to_keyframe/segmentation/<video_stem>/
```

每个视频独立输出，避免同名文件互相覆盖。建议目录结构如下：

```text
segmentation/
  run_001/
    keyframes/
      kf_000001_t_000012.400.jpg
      kf_000002_t_000018.967.jpg
    keyframes.jsonl
    manifest.json
    warnings.log
```

JPG 使用固定质量（默认 95），保持原始 1280x720 尺寸，不在抽帧阶段裁剪 ROI。文件名中的时间戳来自视频帧序号除以实际 FPS，保留毫秒；帧序号从 0 开始并写入元数据。

`manifest.json` 至少记录：输入绝对路径的相对化版本、文件 SHA-256、宽高、FPS、总帧数、时长、脚本版本、参数哈希、输出数量和运行状态。不得写入 API key 等敏感信息。

`keyframes.jsonl` 每行对应一个 JPG，建议字段：

```json
{
  "keyframe_id": "run_001-kf-000001",
  "frame_index": 372,
  "timestamp_sec": 12.4,
  "path": "keyframes/kf_000001_t_000012.400.jpg",
  "trigger": "roi_change",
  "changed_rois": ["hand", "energy"],
  "change_score": 0.183,
  "stable_frames": 5,
  "dedup_distance": null,
  "confidence": "candidate",
  "source": {"video": "run_001.mp4", "sha256": "..."}
}
```

`trigger` 只表示抽取原因，不表示已经识别出游戏事件。初版允许使用 `periodic_anchor`、`roi_change`、`page_change`、`scene_fallback`；页面类型、卡牌 ID 和动作类型留给后续识别阶段。

## 3. 处理流程

### 3.1 启动和输入校验

- 扫描输入目录下的 `.mp4`，按路径排序；支持 `--video` 指定单个文件。
- 用 OpenCV 读取视频元数据，并读取首帧验证可解码。
- 默认严格要求 `1280x720`、`30 FPS`、mp4；FPS 允许 `29.97--30.03` 的容差，尺寸不匹配直接报错并写入 `manifest`，不静默缩放。
- 检查输出目录已有的 `manifest.json`：参数哈希和输入 SHA-256 都相同则跳过，使用 `--force` 才重跑。

### 3.2 粗扫描

- 默认每秒取 2 帧（`--coarse-fps 2`），帧缩放到 320x180 灰度图用于计算。
- 对每个 ROI 计算相邻采样帧的归一化平均绝对差（MAD），并计算全局低分辨率差分。
- 建议首版 ROI 使用归一化坐标，允许通过 JSON 配置覆盖：
  - `top_hud`：左上血量、金币、层数等；
  - `combat_center`：敌人、意图和战斗区；
  - `hand`：底部手牌区；
  - `player_status_left`：左侧角色生命、格挡和状态图标；
  - `player_energy_left`：左下能量区域，避开大部分手牌展开区域；
  - `player_status`（历史兼容名称）：右上角运行元数据、版本号及该区域 HUD 文本；
  - `full_frame`：地图、商店、事件和奖励页面。
- ROI 分数按权重合并。默认 `hand`、`combat_center`、`full_frame` 权重高于 `top_hud`，避免数字动画造成大量误触发。

### 3.3 候选变化和稳定帧

- 当加权变化分数超过 `--change-threshold`，或全局变化超过 `--page-threshold`，建立候选窗口。
- 候选窗口向前保留 `--pre-roll` 秒，向后扫描最多 `--settle-timeout` 秒；默认分别为 0.5 秒和 2 秒。
- 在原始 30 FPS 上检查连续帧。满足“连续 `--stable-frames` 帧变化低于 `--stable-threshold`”时，保存稳定区间的第一帧。默认稳定帧数为 5，约 167 ms。
- 如果超时仍未稳定，保存窗口中变化分数最低的帧，并将 `confidence` 设为 `low`、`trigger` 保持原值；不能静默丢失该变化。
- 候选窗口互相重叠时合并，避免一个动画产生多张相同关键帧。

### 3.4 周期锚点和去重

- 每 `--anchor-interval` 秒（默认 5 秒）保存一张稳定锚点，保证长时间静止页面仍有覆盖；锚点只在与上一张输出的 pHash 距离足够大时写出。
- 对候选帧计算 64 位 pHash；与最近输出帧的汉明距离小于 `--phash-distance`（默认 6）时丢弃。
- 对仍接近但 pHash 不稳定的帧，使用 320x180 灰度 SSIM 复核；SSIM 大于 `--ssim-threshold`（默认 0.985）视为重复。
- 保留候选帧的丢弃记录到 `keyframes.jsonl` 或 `warnings.log`，便于调参时解释召回率下降。

### 3.5 异常和恢复

- 解码失败、坏帧、FPS 不一致和输出写入失败必须记录具体帧号；单帧失败跳过并继续，连续解码失败超过 `--max-decode-errors` 则该视频失败。
- 每处理一帧只更新临时 `manifest.json.tmp`，视频完成后原子改名为 `manifest.json`，支持中断后重跑。
- 单视频失败不阻塞同目录其它视频；进程退出码在全部成功、部分失败、全部失败时分别为 0、2、1。

## 4. 建议实现结构

实现目录建议为 `1_video_to_log/video_to_keyframe/keyframe_extractor/`，使用 Python 3.10+：

```text
keyframe_extractor/
  __main__.py       # python -m keyframe_extractor
  cli.py             # 参数、退出码、批处理
  config.py          # 默认参数和 ROI 配置
  video.py           # 元数据、顺序解码、时间换算
  scores.py          # ROI MAD、全局变化、稳定性
  selector.py        # 候选窗口、稳定帧和周期锚点
  dedup.py           # pHash、SSIM、最近帧索引
  output.py          # JPG、JSONL、manifest 原子写入
  tests/
```

依赖应保持小而稳定：`opencv-python`、`numpy`、`Pillow`（或 OpenCV 自带 JPEG 编码）和测试用的 `pytest`。不要求 PySceneDetect；若启用 scene fallback，应作为可选依赖或调用系统 ffmpeg，并把版本写入 `manifest`。

## 5. CLI 设计

批量运行：

```powershell
cd 1_video_to_log/video_to_keyframe
python -m keyframe_extractor `
  --input-dir .\temp\video `
  --output-dir .\segmentation `
  --config .\config\sts2_720p.json
```

单视频调试和强制重跑：

```powershell
python -m keyframe_extractor `
  --video .\temp\video\run_001.mp4 `
  --output-dir .\segmentation `
  --debug-video `
  --force
```

最少应提供的参数：`--coarse-fps`、`--change-threshold`、`--page-threshold`、`--stable-frames`、`--stable-threshold`、`--anchor-interval`、`--phash-distance`、`--ssim-threshold`、`--roi-config`、`--force`、`--dry-run`。`--debug-video` 只输出候选窗口标注视频或缩略图，不改变正式 JPG 输出合同。

## 6. M1 校验集和验收

M1 录制工具应为每局保存同步真值事件（操作前、操作后或状态边界的时间戳）。评测脚本读取真值时间窗，而不是要求关键帧时间戳精确等于动作时间：

- 召回：每个真值事件窗口内至少有一张 `candidate` 关键帧；
- 稳定性：关键帧不处于明显动画中间帧，连续重复帧率可统计；
- 去重：同一状态在 1 秒内不输出超过一张正式帧，除非 ROI 再次变化；
- 覆盖：静止页面每个锚点间隔至少有一张可用帧；
- 可追溯：每张 JPG 能由 JSONL 反查源视频、帧号、时间、参数和触发 ROI；
- 可恢复：中断重跑不会产生重复或半写文件。

首轮不要预设准确率阈值。先在 20--50 局真值录像上输出基线，分别统计战斗内、地图、奖励、商店和事件页面，再调整 ROI 权重与阈值。若 ROI 差分在真实录屏中无法稳定区分状态，下一步应增加轻量页面分类器或人工校准，而不是继续降低阈值制造更多重复帧。

## 7. 与下游的接口边界

抽帧脚本只负责“证据帧”和 provenance，不负责 VLM 调用、OCR、卡牌/遗物 ID 映射或事件语义推断。`keyframe_to_log` 应读取 `keyframes.jsonl` 中的相对路径和时间戳，并保留 `frame_index`、`trigger`、`changed_rois`、`confidence` 到日志证据字段。

输出目录位于 `video_to_keyframe/segmentation`，属于可再生成产物；若体积较大，应按项目约定保持在 `temp` 或通过 Git 忽略规则排除，不提交视频和 JPG 数据集。
