# 关键帧到日志

本组件假设上游流程已经完成关键帧提取，并将图片保存到指定目录。本组件只负责把已有关键帧转换为结构化日志，不负责读取视频或提取视频帧。

默认适配器使用 OpenAI-compatible 多模态 Chat Completions 格式，因此可以连接云端 VLM、兼容网关或兼容的本地推理服务。每张关键帧会生成一条受约束的结构化观测；响应经过本地校验，并按照图片内容、提示词版本和模型标识进行缓存。

## 无 API 运行

在本目录运行：

    python -m pytest
    python -m keyframe_to_log ..\video_keyframe\run_000 --provider mock

执行 `pip install -e .` 后，也可以使用 `keyframe-to-log` 命令。

## 使用 VLM 运行

必须设置 `STS_VLM_API_KEY` 和 `STS_VLM_MODEL`；`STS_VLM_BASE_URL` 为可选配置。

    $env:STS_VLM_API_KEY = "..."
    $env:STS_VLM_MODEL = "your-vision-model"
    python -m keyframe_to_log ..\video_keyframe\run_000 --provider openai-compatible --patch 0.105.0

关键帧文件名可以包含 `t_12.5`、`time-12.5` 或 `12.5s` 等形式的时间戳。支持 PNG、JPEG、WebP 和 BMP 图片。

程序会自动在每一局关键帧目录中创建 `logs` 文件夹。例如输入目录是 `video_keyframe/run_000`，输出结构为：

```text
video_keyframe/run_000/
├─ frame_000001.jpg
├─ frame_000002.jpg
└─ logs/
   ├─ run_000.json
   ├─ run_000.jsonl
   ├─ run_000.md
   └─ cache/
```

其中：

- `logs/run_000.json`：使用 4 空格缩进的完整结构化日志，供程序和后续数据处理使用。
- `logs/run_000.jsonl`：完整事件流，一行一个事件；逗号和冒号后保留空格，在保持标准 JSONL 的同时提升可读性。
- `logs/run_000.md`：按关键帧分段展示的中文 Markdown 报告，供人工直接阅读。
- `logs/cache/`：VLM 响应缓存，避免相同关键帧重复调用 API。

缓存 JSON 也会使用多行缩进。处理每张关键帧后，程序都会增量保存当前 JSON；即使后续某张图片识别失败，也可以查看已经完成的部分。日志会保留关键帧路径和来源信息，便于人工复核与问题追踪。

程序对 DeepSeek 默认关闭 thinking，因为思考 token 也会占用 `max_tokens`，可能导致还没有输出 JSON 就触发 `finish_reason=length`。如果模型仍返回被截断或无效的 JSON，程序会自动重试最多 3 次，并要求模型缩短回答。仍然失败时，`run_000.json` 和 `run_000.md` 会以 `failed` 状态保存已处理内容以及出错关键帧。可以通过 `STS_VLM_MAX_TOKENS` 调整输出上限，默认值为 `8192`。

识别策略：非地图页面将左上角约 34% 宽、14% 高区域作为 HUD ROI，读取血量、金币、楼层等；战斗页面另裁剪左下角能量宝石 ROI 识别当前能量。地图页面保留整张截图，识别所有可见节点、类型、层级、当前位置和连接路径。


## 对接上游关键帧抽取器

上游 `video_to_keyframe` 的输出目录可以直接作为输入，例如：

```powershell
python -m keyframe_to_log `
  ..\video_to_keyframe\segmentation\run_001 `
  --provider openai-compatible `
  --run-id run_001 `
  --patch 0.111.0
```

程序会读取该目录下的 `keyframes/*.jpg` 和 `keyframes.jsonl`，保留原视频帧号、时间戳、抽帧触发原因等元数据。也可以直接传入 `keyframes` 子目录，程序会尝试读取其父目录中的 `keyframes.jsonl`。

## Spire Codex 卡牌归一化

使用 OpenAI-compatible VLM 时，程序默认从 `https://spire-codex.com` 读取卡牌目录，将手牌和卡牌选项中的 OCR/VLM 名称匹配到规范 `entity_id`。原始识别文本保留在 `raw_name`，不会被覆盖。

可选参数：

```powershell
python -m keyframe_to_log `
    ..\video_keyframe\run_001 `
    --provider openai-compatible `
    --run-id run_001 `
    --patch 0.111.0 `
    --codex-channel beta `
    --codex-version v0.111.0 `
    --codex-lang zhs
```

版本规则：`stable`/`beta` 选择 Codex 数据频道；`--codex-version` 请求指定版本；如果游戏补丁未知或目录版本无法确认，匹配仍会保留，但 `version_status` 会是 `unknown` 或 `unverified`，不会伪装成已验证历史数据。目录缓存在每局的 `logs/codex_cache/`。使用 `--no-codex` 可禁用归一化。
