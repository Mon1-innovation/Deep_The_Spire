# STS2 录屏关键帧抽取

本组件用于从《杀戮尖塔 2》（STS2）MP4 录屏中自动抽取关键帧，为后续关键帧识别和战斗日志生成提供图像证据。本组件只负责抽帧和记录来源信息，不负责识别卡牌、遗物、敌人或具体战斗事件。

## 当前进度

- 已完成基础 ROI 变化检测、候选窗口稳定帧选择、周期锚点、黑屏过滤以及 pHash/SSIM 去重。

- 已加入 shop_decision 商店决策 ROI，并细化 event_options 事件选项 ROI，用于减少商店操作和事件选项选择的漏检。

- 已加入 pseudo_keyframe_fallback beta 功能。启用后，手牌相关变化可以回退到前一个粗采样帧，适合保留抓牌动画开始前仍能看清卡牌的画面；默认开启。

- 已加入 pseudo_keyframe_fallback beta 功能。启用后，手牌相关变化可以回退到前一个粗采样帧，适合保留抓牌动画开始前仍能看清卡牌的画面；仓库提供的 `config/sts2_720p.json` 默认开启，可在自定义配置中关闭。

- 已加入可选战斗开始 OCR，但实测会明显降低速度且未改善战斗中切分；默认关闭，后续不作为常规改进方向。

- 当前配置和实现已通过 Python 编译、配置 JSON 解析及合成帧回退逻辑检查；完整 pytest 测试仍需在安装测试依赖的环境中执行。

详细变更见[视频转关键帧变更日志](../docs/4_video_to_keyframe_changelog.md)。

## 使用方式

在当前目录下运行：

    python -m keyframe_extractor --input-dir .\temp\video --output-dir .\segmentation --config .\config\sts2_720p.json

处理单个录屏时，可以使用：

    python -m keyframe_extractor --video .\temp\video\run_001.mp4 --output-dir .\segmentation --config .\config\sts2_720p.json

如果输出目录中已有相同源文件 SHA-256 且上次处理成功的 manifest.json，程序会自动跳过该视频。使用 --force 可以强制重新处理。

## 输出结构

每个录屏对应一个独立输出目录：

    segmentation/
      run_001/
        keyframes/
          kf_000001_t_000012.400.jpg
        keyframes.jsonl
        manifest.json
        warnings.log

- keyframes/*.jpg：抽取出的关键帧，保持原始 1280x720 尺寸。
- keyframes.jsonl：每行对应一张关键帧，记录帧号、时间戳、触发原因、变化区域、置信度和来源文件。
- manifest.json：记录输入文件 SHA-256、视频尺寸、FPS、帧数、脚本参数、输出数量和处理状态。
- warnings.log：记录尺寸或 FPS 不符合预期、解码异常等警告；没有警告时不会生成。

## 默认配置

config/sts2_720p.json 面向 1280x720、30 FPS 的录屏，包含：

- 粗采样频率、普通页面变化阈值、战斗变化阈值、事件选项变化阈值和商店变化阈值。

- 稳定帧数量、稳定性阈值、周期锚点间隔、pHash/SSIM 去重参数。

- 黑屏识别的平均亮度、标准差和暗像素比例阈值。

- top_hud、combat_center、hand、combat_hand、selection_overlay、deck_overlay、potion_bar、player_status_left、player_energy_left、event_options、shop_decision、player_status 和 full_frame ROI。

- 默认开启的 pseudo_keyframe_fallback（默认作用于战斗场景），以及默认关闭的 battle_start_ocr 功能。

- 默认开启的 pseudo_keyframe_fallback 和默认关闭的 battle_start_ocr beta 功能。

可以复制 JSON 文件后调整参数，或通过 --config 指定自定义配置。ROI 坐标使用 0 到 1 的归一化值，抽帧时不会裁剪最终保存的关键帧。

## 实现边界

实现仅依赖 OpenCV 和 NumPy。程序按视频原始顺序解码，通过 ROI 和全屏变化发现候选状态，在画面稳定后保存关键帧，并使用 pHash/SSIM 去除重复画面。

trigger 只表示抽取原因，例如 roi_change、page_change、periodic_anchor、combat_start_ocr 或带 _pre_coarse 后缀的伪关键帧，不代表已经识别出具体游戏事件。后续 OCR、视觉识别和日志语义推断由 keyframe_to_log 负责。

## 处理选项

- --video 与 --input-dir 互斥；未指定 --video 时，程序按路径顺序处理输入目录下的 MP4。
- --config 指定完整 JSON 配置；--roi-config 可单独指定同格式配置文件。
- --force 强制重新处理已有成功结果。
- --dry-run 只执行抽帧分析并生成元数据，不写入 JPEG 和 JSONL 关键帧内容。

### 新增操作与合并控制

- `selection_overlay`、`deck_overlay`、`potion_bar` 分别关注中央选牌、牌堆平铺和药水栏。

- `pseudo_keyframe_scope` 可设为 `combat`（代码默认；仓库配置使用 `global`）、`decision` 或 `global`，控制伪关键帧回退适用范围。

- `decision_merge_window`、`decision_merge_ssim` 和 `decision_merge_phash_distance` 控制事件、商店、牌组等决策界面的近帧合并。

- 战斗开始 OCR 仅用于实验性定位，保持关闭可避免显著性能损失。
  
  ## 最近行为说明

仓库配置使用 `coarse_fps=16` 和 `stable_frames=3`，用于更好地捕获出牌、选牌等短时且信息密度较高的战斗操作。pHash/SSIM 去重仍然启用，因此这些参数会提高候选帧发现率，但不会输出每一张采样帧。

`pseudo_keyframe_scope` 从 JSON 配置中读取，可设置为 `combat`、`decision` 或 `global`。实际生效的值会写入 `manifest.json`；如果 manifest 是由旧脚本或旧配置生成的，重新处理时请使用 `--force`。
