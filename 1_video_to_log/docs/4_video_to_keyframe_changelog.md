## 2026-09-25 伪关键帧作用域加载与高密度动作采样

### 修复

- 修复配置加载问题，使 `pseudo_keyframe_scope` 能够在运行时生效。`global`、`decision` 和 `combat` 会正确传递给 `Selector`，并写入 `manifest.json`；配置为其他值时会立即报错。
- 修复 `pseudo_keyframe_rois`、`decision_merge_window`、`decision_merge_ssim`、`decision_merge_phash_distance` 和 `decision_merge_rois` 未完整加载的问题，确保配置、实际行为和 manifest 记录保持一致。

### 调整

- 将 `config/sts2_720p.json` 的 `coarse_fps` 从 8 提高到 12，将 `stable_frames` 从 5 调整为 3，以提高出牌、选牌等短时操作被采样到的概率，同时保留 pHash/SSIM 去重和候选帧稳定等待机制。
- 更密的粗采样只会增加候选帧发现率，不会强制输出视觉上重复的画面。如果单段录像的输出量仍然过高，应优先提高 `stable_frames` 或相关变化阈值，不建议直接关闭去重逻辑。

## 2026-09-24 关键帧范围与决策界面合并

- 新增 `selection_overlay`、`deck_overlay` 和 `potion_bar` ROI，覆盖战斗中的中央选牌、牌堆平铺和药水栏变化。
- 新增 `pseudo_keyframe_scope`（`combat`、`decision`、`global`），默认 `combat`；可按需将伪关键帧回退推广到事件、商店和全局关键决策帧。
- 新增决策界面近帧合并参数 `decision_merge_window`、`decision_merge_ssim`、`decision_merge_phash_distance` 与 `decision_merge_rois`，用于抑制地图/牌组滚动和商店动画造成的相近重复帧。
- 战斗开始 OCR 保持默认关闭。根据速度与准确度评估，后续不将 OCR 作为常规战斗切分改进方向。
- `manifest.json` 现在记录伪关键帧范围和决策界面合并参数。

## 2026-09-23 默认启用伪关键帧

- 将 `pseudo_keyframe_fallback` 在程序默认值和 `sts2_720p.json` 中设为开启。
- 检测到手牌区域变化时，默认允许回退到变化前的粗采样帧，降低动画遮挡卡面的风险。
- 保留配置项，设置为 `false` 时仍可关闭。

# 变更日志

## 未发布 - 2026-09-22

### 新增

- 新增 `shop_decision` 商店决策 ROI，并增加独立的商店界面变化阈值。
- 新增 `pseudo_keyframe_fallback` 伪关键帧 beta 开关。启用后，检测到手牌相关变化时可以使用前一个粗采样帧作为关键帧，避免抓牌动画早期画面遮挡卡牌信息；对应的 `trigger` 会追加 `_pre_coarse`。
- 新增可选的战斗开始 OCR 检测，用于识别初始手牌发牌前的“战斗开始”提示。该功能默认关闭，仅在配置启用且环境安装 `pytesseract` 时运行。

### 变更

- 调整默认 `event_options` ROI，使其更集中覆盖事件选项面板，并提高该区域权重，以增强事件选项选择前后的细微变化检测。
- 将商店变化阈值、伪关键帧开关和战斗开始 OCR 开关写入 `manifest.json` 的参数记录。
- 将脚本版本更新为 `0.3.0`。

### 修复

- 修复候选窗口在手牌变化场景下只能保留动画中间帧的问题；beta 模式下可回退到变化发生前的粗采样帧。

### 兼容性

- 仓库提供的 `sts2_720p.json` 默认开启 `pseudo_keyframe_fallback`；自定义配置可关闭，关闭时保持原有关键帧选择行为。
- 战斗开始 OCR 默认关闭，未安装 `pytesseract` 不影响普通抽帧流程。
- `frame_index`、`keyframes.jsonl` 顺序、pHash/SSIM 去重和原始图像尺寸保持原有约定。

## 未发布 - 2026-09-21

### 新增

- 新增黑屏和近黑转场帧检测，支持平均亮度、标准差和暗像素比例配置。
- 新增 `combat_hand` ROI，用于关注战斗中的手牌和出牌区域。
- 新增 `event_options` ROI，用于关注问号事件的选项面板。
- 为普通 ROI、战斗 ROI 和事件选项 ROI 增加独立变化阈值。

### 变更

- 提高默认粗采样频率，降低短暂出牌动作被漏检的概率。
- 让 `combat_hand` 和 `event_options` 使用低于普通页面检测的变化阈值。
- 继续使用单次顺序解码流生成候选帧，不依赖先切分视频再合并结果。

### 修复

- 修复转场黑屏被周期锚点或候选帧保留的问题。
- 修复事件选项选择前后变化较小、导致关键决策帧容易遗漏的问题。
- 修复战斗出牌局部变化被全屏变化阈值过滤的问题。

### 兼容性

- `frame_index` 和 `keyframes.jsonl` 的记录顺序继续与原视频一致。

- pHash/SSIM 去重逻辑保持不变。

- 抽帧脚本只负责保留图像证据和来源信息，不负责判断具体游戏语义；卡牌、事件和其他动作的识别由后续流程完成。   
