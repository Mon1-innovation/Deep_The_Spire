# 关键帧到日志：首版实现

> 日期：2026-09-15
> 范围：只处理已经生成的关键帧，不负责视频读取、视频切分、抽帧、稳定帧检测或关键帧筛选。

## 目录与入口

实现位于 `1_video_to_log/keyframe_to_log`。默认约定关键帧由上游放入 `1_video_to_log/video_keyframe`，但命令行也允许指定其它输入目录。

从 `1_video_to_log/keyframe_to_log` 运行：

```powershell
python -m keyframe_to_log ..\video_keyframe\run_000 --provider openai-compatible
```

## 已实现流程

1. 递归读取输入目录中的 PNG、JPEG、WebP、BMP 图片，不修改原图。
2. 从文件名读取时间戳并排序；支持 `t_12.5`、`time-12.5`、`12.5s`，无时间戳时按文件顺序生成顺序时间。
3. 通过 OpenAI-compatible 多模态 Chat Completions 接口调用 VLM；接口可以指向云端服务、兼容网关或兼容的本地服务。
4. 要求模型输出受 JSON Schema 约束的页面类型、玩家、敌人、手牌、遗物、药水、牌堆计数、选项、可见动作、置信度和证据。
5. 在本地校验页面类型、置信度范围和字段类型；不合格结果不会被静默写入日志。
6. 按图片内容、prompt 版本和模型标识缓存结果，避免调试和重跑时重复付费。
7. 在每局关键帧目录中自动创建 `logs` 子目录，集中保存完整 JSON、JSONL、Markdown 和 `cache` 缓存目录。
8. 导出使用 4 空格缩进的 observation-first JSON 日志，并额外导出一行一个事件的 JSONL；JSONL 在逗号和冒号后保留空格，兼顾标准格式和人工可读性。
9. 非地图帧使用左上 HUD ROI 单独识别血量、金币、能量等数值；地图帧使用整屏识别所有可见节点和连接路径。
10. 同步生成适合人工阅读的中文 Markdown 报告；每完成一张关键帧都会增量保存 JSON 和 JSONL，处理中断时仍可查看已完成部分。

## 现成能力的复用方式

首版不自行实现或绑定一个大型视觉模型，而是复用 OpenAI-compatible 多模态调用协议和服务端结构化输出能力。这样可以替换不同的云端 VLM、兼容网关或本地推理服务，而无需修改日志流水线。

后续实体识别应接入 STS2 元数据项目形成 `图像候选 -> 实体 ID -> 版本化元数据`，避免把卡牌描述的 OCR 文本当作事实。该部分需要先确定元数据快照来源、游戏 patch 和关键帧语言，当前首版不伪造这些映射。

## 环境变量

- `STS_VLM_API_KEY`：必填，VLM 服务密钥。
- `STS_VLM_MODEL`：必填，具体视觉模型名称；缓存键会包含该名称。
- `STS_VLM_BASE_URL`：可选，默认 `https://api.openai.com/v1`。

## 当前边界

- 单张关键帧只能证明画面中可见的状态；无法可靠确定的动作应输出 `null`，而不是猜测。
- 首版只做通用页面观测和基础事件化，尚未实现相邻帧状态差分、能量/牌堆不变式、卡面向量检索、STS2 patch 元数据归一化。
- 仓库当前没有实际关键帧和 API 密钥，因此已完成 mock 端到端验证，但尚未对真实 STS2 画面测量字段准确率。

## 验证结果

在 Python 3.8 环境运行：

```text
3 passed
mock smoke test: 1 observation, 2 events
```
