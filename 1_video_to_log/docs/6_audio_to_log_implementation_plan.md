# STS2 录像音频转战斗日志：查证、方案与验证

> 状态：方案定稿，未新增音频实现代码
> 
> 适用范围：单人 STS2 录像；输入可以是带音轨的视频，也可以是独立音频；输出保持 `0_combat_log_format.md` 的 JSONL 事件流。

## 1. 结论

目前没有发现可以直接把 STS2 主播录像转换为“游戏状态、玩家动作、口述决策理由”完整日志的成熟开源项目。现有 STS2 项目主要提供游戏数据字典、游戏内日志/遥测或 agent 轨迹，不能替代录像中的音频时间轴和主播口述。

建议采用**独立音频流水线，再按时间合并**的方案：

```text
video/audio
  -> ffmpeg 音频规范化（保留源视频时间基准）
  -> VAD + ASR（WhisperX；资源受限时 faster-whisper）
  -> 词级/片段级时间戳、语言、置信度、原文
  -> 语音片段合并为 reasoning 候选
  -> 与现有 keyframes.jsonl / run.json 事件按时间窗口关联
  -> 输出 reasoning JSONL（可独立复核）
  -> 稳态合并为最终 combat log JSONL
```

音频只负责回答“玩家说了什么、什么时候说的”；画面观测、卡牌/遗物元数据、状态机和不变式负责回答“游戏发生了什么”。ASR 不能推断玩家实际采取了某个动作，也不能用口述内容覆盖视觉证据。

## 2. 复用项目查证

| 项目                                                          | 可复用部分                                                           | 限制与决定                                           |
| ----------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------- |
| [WhisperX](https://github.com/m-bain/whisperX)              | Whisper ASR、VAD、wav2vec2 强制对齐、词级时间戳；可选 pyannote diarization     | 依赖 PyTorch/模型下载；中文词级边界受对齐模型支持影响；作为首选音频后端        |
| [OpenAI Whisper](https://github.com/openai/whisper)         | 多语言 ASR、`word_timestamps`、`initial_prompt`                      | 原生词级时间戳是推理时对齐，长音频和停顿处精度有限；可作基线或无 WhisperX 环境的后备 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | CTranslate2 推理、较低资源占用、segment/word timestamps、VAD 过滤            | 词级时间戳仍不是事实真值；适合 CPU/显存受限批处理                     |
| ffmpeg                                                      | 从视频抽取单声道 PCM、读取音频时长、保持时间基准                                      | 只做媒体处理，不负责语义识别                                  |
| 项目现有 `video_to_keyframe`                                    | `manifest.json`、`keyframes.jsonl`、源视频 SHA256、秒级 `timestamp_sec` | 直接作为对齐索引，不重做视频解码                                |
| 项目现有 `keyframe_to_log`                                      | 观测缓存、`events` JSONL、`t` 字段、`reasoning` 事件兼容格式                   | 需要新增合并步骤，不能把音频文本硬塞进 observation state           |

Whisper 官方实现公开了 `word_timestamps` 选项及词级 `start/end` 计算方式；官方文档也说明 OpenAI 音频 API 的词/片段时间戳需要选择相应粒度。WhisperX 论文和仓库的核心改进是 VAD 加 wav2vec2 强制对齐，适合本项目需要的时间定位；faster-whisper 则适合先建立低成本基线。上述项目都不是 STS2 专用项目，因此不应期待它们识别卡牌、战斗状态或决策因果。

## 3. 输入与时间基准

### 3.1 媒体规范化

先用 ffprobe 记录源媒体的 `duration`, `start_time`, 音频流 `sample_rate`, `channels` 和视频流 `time_base`。随后抽取：

```powershell
ffmpeg -i input.mp4 -map 0:a:0 -ac 1 -ar 16000 -c:a pcm_s16le audio.wav
```

如果视频有非零起始时间、剪辑拼接或变速，必须把 `source_offset_sec`、`speed_factor`、`segments` 写入 manifest；不能假定字幕时间戳天然等于视频帧时间戳。首期质检应拒绝变速、音画不同步、无音轨和严重剪辑的素材。

### 3.2 与现有输出的关联键

现有 `keyframes.jsonl` 已输出 `timestamp_sec`、`frame_index`、`keyframe_id` 和源视频 SHA256；现有 `keyframe_to_log` 事件使用 `t`。合并前统一为浮点秒 `t`，并保留：

```json
{
  "video_t": 134.20,
  "audio_start": 133.84,
  "audio_end": 135.12,
  "keyframe_ids": ["run_001-kf-000057"],
  "alignment_method": "overlap+nearest_state",
  "alignment_confidence": 0.87
}
```

若容器时间戳与抽帧时间轴不一致，以源视频 PTS 为主；合并器应在输入阶段检查 `keyframes.jsonl` 是否单调，并按 `timestamp_sec` 排序后再匹配。发现重复、倒序或超出视频时长的时间戳时写入 warning，不能静默修正。

## 4. 音频流水线

### 阶段 A：ASR 原始产物

首选 WhisperX：

1. VAD 找到语音区间，减少游戏音效和长静音造成的幻觉。
2. Whisper 转写，固定 `language=zh`（混合语言素材允许 `auto`，但必须记录检测结果）。提示词加入 STS2 专有词、卡牌名、角色名、常见口头语。
3. wav2vec2 对齐，生成词级 `start/end/score`；保留原始 segment，便于人工回听。
4. 只有明确存在多位说话人时才启用 diarization。默认把唯一稳定说话人映射为 `player`；旁白、来宾和视频音频应标成 `other`，不进入 reasoning。

建议的独立产物 `audio/transcript.json`：

```json
{
  "schema_version": "audio-transcript-1",
  "source": {"video_sha256": "...", "audio_sha256": "...", "offset_sec": 0.0},
  "backend": {"name": "whisperx", "model": "large-v3", "align_model": "...", "language": "zh"},
  "segments": [
    {
      "id": "asr-000042", "start": 133.84, "end": 135.12,
      "text": "家人们，我先看一眼地图再抓",
      "speaker": "player", "confidence": 0.87,
      "words": [
        {"text": "家人们", "start": 133.84, "end": 134.20, "score": 0.91},
        {"text": "我先", "start": 134.24, "end": 134.50, "score": 0.89}
      ]
    }
  ]
}
```

ASR 原文、词级时间戳和模型版本必须保留，即使后续清洗失败也不能只留下最终 reasoning 文本。

### 阶段 B：候选 reasoning 片段

以语音区间为单位合并相邻 segment：间隔不超过 0.8 秒、同一 speaker、不是纯笑声/口头填充词。不要按固定时长硬切，因为“先看地图……所以走左边”应保留为一条可解释理由。

候选过滤规则：

- `speaker != player`：标记 `excluded`，不生成 player reasoning；
- 无有效词级时间戳：降级为 segment 时间，`timing_quality=segment`；
- ASR 低置信度、重复文本、静音幻觉：保留在 transcript，reasoning 事件标记 `needs_review`；
- 与视频中断/剪辑重叠：不自动归属任何动作。

### 阶段 C：与游戏事件对齐

每个候选 reasoning 先按窗口匹配事件：

1. 取候选 `[start,end]` 与事件时间 `t` 的重叠；
2. 若没有重叠，取 `reasoning.end <= action.t` 且距离最小的动作，允许默认最多 8 秒；
3. 若同时接近多个动作或跨越页面切换，保持 `action_ref=null`，仅作为时间标记的独立 reasoning；
4. 关联结果带 `alignment_confidence`，禁止把最近动作当成确定因果。

推荐的置信度分解：`0.45 * timing_quality + 0.35 * event_proximity + 0.20 * speaker_confidence`。这是排序/质检分数，不是模型校准后的概率。

## 5. 最终 JSONL 事件契约

保持人类规范中的 `by/type/message` 结构，在 reasoning 事件上增加可选时间和证据字段：

```json
{"id": 42, "by": "player", "type": "reasoning", "t": 134.20, "message": "家人们，我先看一眼地图再抓", "audio": {"segment_id": "asr-000042", "start": 133.84, "end": 135.12, "timing_quality": "word", "speaker": "player", "asr_confidence": 0.87}, "action_ref": null, "alignment_confidence": 0.87}
```

`t` 定义为口述片段的锚点时间，默认取最后一个有效词的 `end`；同时保存完整 `audio.start/end`，支持回放。若理由明确发生在动作前，应保留 `action_ref` 指向随后动作，但不能改变事件顺序。最终 `events` 按 `(t, id)` 稳定排序，原有 world/player action/response 事件不改语义。

音频事件应插入已有 `events`，但不要在 `observations[*].state` 中写入自然语言理由。这样可以分别训练状态/动作任务和理由生成任务，也便于重新运行 ASR 而不重新调用 VLM。

## 6. 工程接口与目录建议

新增独立包（建议 `1_video_to_log/audio_to_reasoning/`），不修改现有两个包的核心接口：

```text
audio_to_reasoning/
  cli.py          # extract / align / merge 子命令
  media.py        # ffprobe/ffmpeg、hash、offset
  asr.py          # WhisperX/faster-whisper adapter
  segments.py     # VAD segment 合并与质量标注
  align.py        # 与 keyframes.jsonl / run.json 关联
  schema.py       # transcript/reasoning 校验
```

建议命令：

```powershell
python -m audio_to_reasoning.extract input.mp4 --out run_001/audio/transcript.json --backend whisperx --language zh
python -m audio_to_reasoning.align run_001/audio/transcript.json run_001/keyframes.jsonl --out run_001/audio/reasoning.jsonl
python -m audio_to_reasoning.merge run_001/logs/run_001.json run_001/audio/reasoning.jsonl --out run_001/logs/run_001_with_reasoning.jsonl
```

每一步都应幂等：输入媒体/模型/参数哈希作为缓存键；失败时保留已完成 JSONL 和 manifest。云端 ASR 可以作为 adapter，但原始音频可能包含隐私，默认优先本地 WhisperX；云端方案必须在 manifest 中写明服务、模型和数据上传范围。

## 7. 质量闸门与人工复核

必须至少检查：

1. `audio_sha256`、视频 SHA256 与 keyframe manifest 一致；
2. segment `start < end`、词级时间戳落在 segment 内、无 NaN/负数；
3. reasoning 与事件按时间排序，关联窗口内没有两个冲突动作；
4. 语音覆盖率、VAD 语音时长、低置信度比例、未关联 reasoning 数量；
5. 抽样回听：至少覆盖低置信度、跨页面、动作前理由和多人说话场景；
6. 以模组真值日志同步录制的校验集评估“理由时间命中率”和“player speaker precision”，不能只看 WER。

建议先定义可接受基线，再扩大规模：`reasoning_time_hit@2s`、`reasoning_time_hit@5s`、动作前/后顺序准确率、说话人精确率、人工确认后可用率。ASR WER 只能衡量文字，不代表决策理由是否对齐。

## 8. 对现有项目的验证结果

- `video_to_keyframe` 的样例 manifest 声明源视频为 1280x720、30 FPS、153.17 秒、75 个关键帧；`keyframes.jsonl` 每条包含 `timestamp_sec`、`frame_index`、`keyframe_id` 和源 SHA256，满足音画对齐所需的索引条件。
- `keyframe_to_log` 的 pipeline 已按关键帧时间生成 `events`，其中 action/response 均有 `t`；因此无需改变现有视觉观测 schema，只需在最终事件流插入 reasoning。
- 已在当前 Python 环境补装 `pytest` 并执行现有测试套件：`1_video_to_log/keyframe_to_log` 为 **16 passed in 0.09s**，`1_video_to_log/video_to_keyframe` 为 **9 passed in 3.11s**。普通沙箱运行时 pytest 的临时目录清理受到 Windows 权限限制；使用已授权的提升权限重跑后完整通过。音频实现阶段仍需增加 transcript schema、时间对齐和端到端合并的 fixture 测试。

## 9. 分阶段落地

1. **MVP**：本地 WhisperX/faster-whisper 输出 transcript；不做语义归因，只导出带时间的 `reasoning`。
2. **对齐版**：接入 `keyframes.jsonl` 和现有 `run.json`，实现窗口匹配、`action_ref`、冲突降级和回放链接。
3. **质量版**：建立 20–50 局同步录像/模组真值集，评估时间命中率和说话人精度，校准窗口与阈值。
4. **规模版**：增加缓存、批处理、并行 GPU、云端 ASR adapter；仍保留本地可复核 transcript。

该路线既复用了已有关键帧和日志基础设施，也保留了音频独立重跑能力；最关键的设计约束是：**reasoning 是带证据和时间范围的观测事件，不是由 ASR 推断出的游戏事实**。
