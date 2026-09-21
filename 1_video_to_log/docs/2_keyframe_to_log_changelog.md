# 关键帧到日志变更记录

## 2026-09-18

### Spire Codex 卡牌归一化

- 接入 `spire-codex.com/api/cards`。
- 支持 `zhs` 中文目录、`stable`/`beta` 频道和可选指定版本。
- 保留 `raw_name`，并补充 `entity_id`、`canonical_name`、`display_name`、卡牌类型、稀有度、费用和描述。
- 匹配状态区分 `matched`、`ambiguous`、`not_found`。
- 版本状态区分 `verified`、`unverified`、`mismatch`、`unknown`。
- Codex 目录按每局缓存，网络不可用时保留 OCR 结果并继续生成日志。
- 观测结构版本升级到 `5`，缓存版本升级到 `observation-v5`。

### 仍需注意

- stable 当前接口未必携带精确历史补丁号；没有可验证目录版本时不会标记为 `verified`。
- 训练数据应优先使用 `version_status=verified` 的实体字段；其他情况保留为候选或人工复核。


## 2026-09-21 上游抽帧器适配

- 兼容上游 video_to_keyframe 生成的 keyframes 目录和 keyframes.jsonl 清单。
- 支持解析 kf_000001_t_000012.400.jpg 文件名中的帧号与时间戳。
- 将抽帧触发原因、原视频帧号等元数据保留到日志观测的 keyframe_metadata。
- 观测缓存和观测结构版本升级到 observation-v6 / 6。
