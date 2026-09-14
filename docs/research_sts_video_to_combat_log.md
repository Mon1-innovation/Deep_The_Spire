# 杀戮尖塔实况录像 → 规范战斗日志：项目调研与方向规划

> 调研日期：2026-09-14 ｜ 状态：仅调研与规划，未开始编码 ｜ 选型已确认（见 §6、§7）
> 目标：把网络主播的《杀戮尖塔 1/2》实况录像，自动转写为可供深度学习使用的结构化战斗日志。
> 约束：无游戏内模组接入（数据源是视频流）；不训练/微调 VLM（定位为"前置任务"，不做重资产投入）。
> 已确认：**STS2 · 整局覆盖 · 云端 VLM API · 自有 GPU 用于后续微调**

---

## 0. 结论速览

1. **没有现成的"STS 录像 → 战斗日志"端到端开源项目。** 但存在 4 类可直接复用的组件 + 2 篇高度同题的学术工作可以照抄设计。
2. **端到端"把 30 分钟视频丢给 VLM 输出日志"这条路要放弃。** ACL 2026 的 [GameplayQA](https://arxiv.org/abs/2603.24329) 实测表明：前沿 MLLM 在**决策密集的游戏 POV 视频**上，时间定位、跨视频对齐、角色归属都会系统性出错，与人类差距显著。必须拆解。
3. **正确的形态是：游戏语义驱动的事件切分 + ROI 化的小问题 VLM 调用 + 状态机/不变式校验。**
   通用"关键帧抽取"算法（PySceneDetect 等）在这里**不是主引擎**——尖塔的 UI 画面几乎不换镜头，帧间差异小，场景检测器会失效。真正有效的是"**状态稳定帧**"检测（帧差分 / pHash / SSIM 去重），触发器来自游戏语义 ROI。
4. **卡牌描述不要走 OCR。** 尖塔卡牌是有限闭集（几百张），应做"**缩略图检索 → ID → 查元数据表**"，把文字识别误差降到 0。STS2 全量数据已有社区反编译 API：[ptrlrd/spire-codex](https://github.com/ptrlrd/spire-codex) / [spire-codex.com](https://spire-codex.com/about)。
5. **最被低估的一步：自建"带模组真值"的小数据集。** 用 [STS2CombatLogMod](https://www.nexusmods.com/slaythespire2/mods/100) 之类模组自己录几十局"真值日志 + 同步录屏"，用来校准和评测视频管线。**没有这个校验集，整条链路无法判断精度。**
6. **先想清楚视频路线的独特价值。** 若最终只需要 `(state, action)` 对，尖塔 1 社区已有大规模 run history 数据集（[MaT1g3R/Slay-the-Spire-data](https://github.com/MaT1g3R/Slay-the-Spire-data)、[AgenticSTS-trajectories](https://huggingface.co/datasets/AlayaLab/AgenticSTS-trajectories)、[Orak](https://huggingface.co/datasets/KRAFTON/Orak)）。**视频路线不可替代的价值在于：主播口述的决策理由（音频）+ 真实人类操作时序 + 画面层面的临场信息**。这决定了 schema 设计重心。

---

## 1. 直接相关：尖塔数据 / Agent 生态

| 项目 | 性质 | 对本项目的用处 |
|---|---|---|
| [**Spireeval** (ICDMW 2025)](https://www.computer.org/csdl/proceedings-article/icdmw/2025/813200c404/2eP1Asezxfi) | 论文：Transforming Gameplay into Sequential Datasets for LLM Decision-Making Analysis | **同题度最高**。把对局转为"序列化数据集"做 LLM 决策分析。虽然其数据来源不是主播视频，但其 **schema、切分粒度、"什么才算一个决策步"** 的定义应直接借鉴。建议优先拿到全文。 |
| [**Orak** (ICLR 2026, KRAFTON)](https://proceedings.iclr.cc/paper_files/paper/2026/hash/63506d49e90266a51f21ba8edbd49f46-Abstract-Conference.html) · [HF](https://huggingface.co/datasets/KRAFTON/Orak) | 多游戏 LLM Agent 基准，含 `slay_the_spire` 子集（1002 条轨迹） | 提供**轨迹格式参考**与"决策标签长什么样"的实例；也可作为下游任务的评测集。 |
| [AlayaLab/AgenticSTS-trajectories](https://huggingface.co/datasets/AlayaLab/AgenticSTS-trajectories) · [AgenticSTS](https://github.com/AlayaLab/AgenticSTS) | HF 上的 STS 轨迹数据集 | 同上，可直接对拍字段设计。 |
| [**ptrlrd/spire-codex**](https://github.com/ptrlrd/spire-codex) · [站点](https://spire-codex.com/about) | 反编译 STS2 后的**数据 API + 网站**（卡牌/遗物/怪物等），并托管对局提交与排行榜 | **本项目的"词典"和 ground truth 元数据源**。所有 OCR/VLM 输出最终都要归一到这里的 ID。 |
| [MaT1g3R/Slay-the-Spire-data](https://github.com/MaT1g3R/Slay-the-Spire-data) · [rrenaud/slay_analysis](https://github.com/rrenaud/slay_analysis) | STS1 run history 数据与分析脚本 | 证明"文本级真值"已很丰富；用于评估视频路线是否值得做。 |
| [STS2CombatLogMod](https://www.nexusmods.com/slaythespire2/mods/100) / [Simple Combat Log](https://www.nexusmods.com/slaythespire2/mods/928) / [AnalyticsTelemetry](https://www.nexusmods.com/slaythespire2/mods/479) | Nexus 上的 STS2 战斗日志类模组 | **不能用于主播录像，但可用于自建校验集**（见 §4 阶段 0）。 |
| [S0ul3r/BoberInSpire](https://github.com/S0ul3r/BoberInSpire) | C# + Python 的 STS2 战斗助手 | 说明社区已有"屏幕读取 + 实时建议"的需求与实现，可参考其屏幕解析思路。 |
| [Yidhar/sts2-mcp](https://github.com/yidhar/sts2-mcp) · [katherine-atwell/slay-the-spire](https://github.com/katherine-atwell/slay-the-spire) | MCP 接入 / 微调 LLM agent | 下游消费方参考：日志 schema 要能被这类 agent 直接吃。 |
| [t22000t/slay-the-spire-1-card-multimodal-embeddings](https://huggingface.co/datasets/t22000t/slay-the-spire-1-card-multimodal-embeddings) | 卡牌图文 embedding 数据集 | 支撑"**卡面缩略图 → 卡牌 ID**"的检索式识别，替代 OCR。 |
| [Sts2 Vision](https://clawbox.com/zh/store/app/sts2-vision)（OpenClaw 商业 skill） | 屏幕捕获 + OCR 的 STS2 实时 DPS 监控 | 存在同类商业实现，说明屏幕解析可行；闭源、硬件绑定，只能作参考。 |

---

## 2. 方法论最接近：screencast → 结构化动作日志

这一类是**本项目真正的"技术原型"**，比尖塔专属项目更有指导价值。

- [**SeeAction** (ICSE 2025 杰出论文)](https://arxiv.org/abs/2503.12873) — 从录屏**逆向工程**出 `[command] [widget] [location]` 三元组结构的用户动作；11 类命令 × 11 类控件；自建 7260 视频-动作对；两阶段（先定位 UI 元素，再判定动作类型）+ 多任务联合学习。
  → **这正是"录像 → 动作日志"的学术范式**，建议全文精读。它的"非侵入式、不依赖 OS/无障碍接口"假设与我们的约束完全一致。
- [**GameplayQA** (ACL 2026)](https://arxiv.org/abs/2603.24329) — 多人 3D 游戏 POV 视频，以 **1.22 labels/秒** 的密度标注 state/action/event，按 `Self / Other Agents / World` 三元结构组织；2.4K 诊断 QA。
  → 两个用处：(a) 给出"决策密集视频"的**标注 schema 与粒度**参考；(b) 它的失败分析是**风险清单**——MLLM 在时间定位与角色归属上会错，我们必须用结构化手段兜住。
- [ServiceNow/VideoCUA](https://huggingface.co/datasets/ServiceNow/VideoCUA) · [Video2GUI (ICML 2026)](https://huggingface.co/papers/2605.14747) — 从视频合成 GUI 交互轨迹；同样的"视频→轨迹"思路，可借鉴其轨迹表示。
- [GameVerse: Can VLM Learn from Video-based Reflection?](https://arxiv.org/html/2603.06656) — VLM 从游戏视频反馈中学习。
- [microsoft/OmniParser v2](https://github.com/microsoft/OmniParser) · [HF](https://huggingface.co/microsoft/OmniParser-v2.0) — 纯视觉 GUI parsing（图标检测 + 语义描述），输出可交互元素列表。**用于手牌/按钮/意图图标的定位与枚举**。
- [docling-project/ScreenVLM](https://huggingface.co/docling-project/ScreenVLM) — 屏幕理解专用 VLM（Apache-2.0）。
- [PaddleOCR-VL](https://github.com/PaddlePaddle/PaddleOCR)（0.9B） — 超轻量文档/版面解析，若确需 OCR（如伤害数字、HP、层数）是性价比之选。
- [Qwen3-VL](https://mintlify.wiki/QwenLM/Qwen3-VL/concepts/key-features) 系列 — 具备 grounding/坐标定位与结构化输出能力；社区已有[游戏 UI OCR 微调小模型](https://huggingface.co/saengha/qwen3-vl-2b-finetuned-korean-game-ui-ocr)（说明"小模型 + 游戏 UI"是可行路线）。

---

## 3. 关键帧抽取：这是需要重点厘清的方向

### 3.1 通用工具（事实标准）
- [**PySceneDetect**](https://www.scenedetect.com/docs/head/api/detectors.html) — `ContentDetector`（内容变化）、`AdaptiveDetector`（抗运动/抖动）、`ThresholdDetector`（淡入淡出）；Python API + CLI，最成熟。
- ffmpeg `select='gt(scene,0.1)'` — 无依赖兜底方案。
- [davidhc1230/Video_Page_Extractor](https://github.com/davidhc1230/Video_Page_Extractor) — **专抽"稳定帧"**，用 pHash + SSIM 去重，面向 PPT/文档/动画截图场景。
- [iejMac/video2dataset](https://github.com/iejMac/video2dataset) — 视频切分 + 抽帧的工程胶水，适合批量流水线。
- [VLM-AutoYOLO](https://github.com/Somnusochi/VLM-AutoYOLO) — VLM 预标注 → 人工修正 → 训练检测器的闭环（可用于"手牌图标检测器"的半自动标注）。

### 3.2 学术上的"自适应/查询感知选帧"（选读）
- [LENS: Adaptive Spatio-Temporal Zooming (ECCV 2026)](https://github.com/zhangce01/LENS)
- [FOCUS: Efficient Keyframe Selection for Long Video Understanding (ICLR 2026)](https://proceedings.iclr.cc/paper_files/paper/2026/hash/a010577f93a8301dada61f0b97cda923-Abstract-Conference.html)
- [Coverage-Driven Adaptive Keyframe Selection](https://arxiv.org/html/2608.00714v1) · [HiMu: Hierarchical Multimodal Frame Selection](https://paperswithcode.co/paper/2603.18558)
- [From Frames to Clips: Efficient Key Clip Selection](https://www.scilit.com/publications/8bebe9802df3fc220cd9e4ab26f4ece2)

**判断：** 这些工作解决的是"**在不知道看什么时，如何少喂帧**"。而本项目的关键帧是**语义已知的**——我们知道要找的是"回合开始""手牌已发完""敌人意图已显示""奖励选项已展开"。因此：

> **不要用通用选帧算法做主切分，要用游戏语义事件驱动切分；通用算法只作为兜底和去重手段。**

### 3.3 尖塔场景下的关键帧定义（建议）
尖塔 UI 的特性：**无镜头切换、局部区域跳变、状态持续数秒到数十秒**。因此：

1. **页面级切分（粗）**：低分辨率 + 每 1–2s 采样，判定当前是 地图/战斗/商店/事件/篝火/奖励/卡组/遗物 中的哪一类。可用极小分类器（帧级 CNN）或廉价 VLM。
2. **战斗内状态切分（细）**：对若干 ROI（能量数字、手牌区、HP 条、格挡、敌人意图、抽/弃牌堆计数）做逐帧差分；**"变化结束后的第一个稳定帧"= 一个状态边界**。这比整帧 pHash 敏感得多，也便宜得多。
3. **动作时刻定位**：出牌动画 / 卡牌高亮 / 鼠标指针位置变化 → 定位 `card_played` 的时刻，**不让 VLM 去"猜"发生了什么**。
4. **去重**：同一状态连续 N 帧只保留一帧；pHash/SSIM 兜底。

---

## 4. 方向规划（分阶段）

> 总体架构：`视频 → 页面切分 → ROI 状态边界 → 结构化观测 → 事件重建与校验 → JSONL 日志`
> 核心原则：**VLM 是"观测器"，不是"事实来源"；事实由元数据表 + 状态机 + 不变式决定。**

### 阶段 0｜地基：元数据 + Schema + 校验集（1–2 周）
- 从 [spire-codex](https://github.com/ptrlrd/spire-codex) 拉取全量卡牌/遗物/药水/怪物/事件数据；建立 `ID ↔ 多语言名 ↔ 卡面缩略图` 索引。**带 patch 版本号**（STS2 处于 Early Access，数值随版本变动）。
- 定义战斗日志 schema（对齐 Spireeval / Orak 的轨迹表示）：以 **事件流**（event stream）为主，而不是"每帧状态快照"。
- **自建校验集**：用战斗日志模组自录 20–50 局，得到"真值日志 + 同步录屏"配对。这是后续一切精度指标的基础。

### 阶段 1｜视频预处理与关键帧（核心攻坚）
- 时间轴粗切分（页面类型）→ 战斗段细切分（ROI 状态边界）→ 稳定帧筛选。
- 可选：手牌图标检测器（YOLO/模板匹配），用 VLM-AutoYOLO 式闭环半自动标注。
- 产出：每局数百至数千帧（含时间戳、页面类型、ROI 摘要），并附带"为什么选它"的触发原因，便于回溯。

### 阶段 2｜结构化抽取（VLM 尽量少用、用对地方）
- **分层提问**：裁剪 ROI → 一次只问一个小问题（"能量数值是多少"），而不是整帧问"现在什么局面"。
- **手牌识别走检索不走识别**：卡面缩略图 → embedding 最近邻 → 卡牌 ID → 元数据取描述。
- **仅歧义时调用 VLM**：ROI 规则无法判定时才升级。
- 强约束输出（JSON Schema / 受限解码），结果缓存，同一帧幂等不重算。

### 阶段 3｜事件重建与校验
- **状态机**：由相邻稳定状态 + 元数据反推动作（例：能量 3→1、手牌少一张「重击」、敌人 HP-8 且获得易伤 → 判定为"打出重击"）。
- **不变式校验**：能量守恒、抽/弃/手牌数守恒、HP 变化范围、回合数单调、格挡结算顺序。任一项失败 → 该步降级为"低置信/待人工"。
- **音频（Whisper / faster-whisper / [WhisperX](https://github.com/m-bain/whisperX)）**：转写 + 词级时间戳，与决策时刻对齐，写入 `commentary` 字段。
  → **音频只作为"理由/意图"字段，不参与状态重建**，避免污染结构化真值。

### 阶段 4｜导出与质检
- 导出训练用 JSONL；抽样 1–2% 人工复核；做**重放一致性检查**（用日志喂轻量模拟器，看能否复现 HP/能量/牌堆），这是最强的质量闸门。
- 产出置信度分层：`verified` / `inferred` / `uncertain`，下游可按需过滤。

### 建议的日志 schema（草案）
```jsonc
{
  "run_id": "...", "game": "sts2", "patch": "0.105.0", "ui_language": "zhs",
  "video": { "source": "twitch", "url": "...", "fps": 60, "resolution": "1920x1080" },
  "events": [
    { "t": 0.0,   "type": "run_start", "character": "Ironclad", "ascension": 10 },
    { "t": 123.4, "type": "map_choice", "floor": 5, "options": ["combat","shop","elite","rest"], "chosen": "elite" },
    { "t": 130.2, "type": "combat_start", "encounter": "Jaw Worm", "deck": ["Strike","Strike","Defend"] },
    { "t": 135.0, "type": "turn_start", "turn": 1, "energy": 3,
      "hand": ["Strike","Defend","Bash","Strike","Defend"],
      "enemy": { "hp": 44, "block": 0, "intent": "attack_11" },
      "piles": { "draw": 4, "discard": 0, "exhaust": 0 } },
    { "t": 137.1, "type": "card_played", "card_id": "Bash", "target": "Jaw Worm", "cost": 2,
      "observed_effects": [ { "enemy_hp": [44, 36] }, { "status_applied": ["Vulnerable", 2] } ] }
  ],
  "commentary": [ { "t": 134.2, "text": "这里先上易伤", "asr_conf": 0.82 } ],
  "provenance": { "frame_ts": 137.05, "extractor": "vlm:qwen3-vl-4b", "confidence": 0.93,
                  "verified_by": ["inv_energy", "inv_piles"] }
}
```

---

## 5. 风险清单

| 风险 | 说明 | 对策 |
|---|---|---|
| **端到端 VLM 幻觉** | MLLM 在决策密集游戏中时间定位/角色归属会错（[GameplayQA](https://arxiv.org/abs/2603.24329) 结论） | 拆分为观测 + 重建；状态机 + 不变式校验；置信度分层 |
| **卡牌文字 OCR 不稳** | 字体/分辨率/UI 缩放/语言差异 | 不做 OCR，做**缩略图检索 + 元数据查表** |
| **版本漂移** | STS2 仍在 Early Access，补丁频繁改数值/UI | 元数据与日志均带 patch 版本；按版本隔离 |
| **多人合作模式** | STS2 有 4 人合作，UI 布局更复杂 | 一期只做单人；多人作为后续 |
| **主播视频非标准** | 分辨率、UI mod、画中画/cam、弹幕遮挡、剪辑加速、语言混杂 | 前置质检：检测并丢弃不合格片段；多语言元数据 |
| **计算预算** | 300 帧/局 × 多 ROI × 多局 = 百万级调用 | ROI 化 + 检索替代识别 + 结果缓存 + 只对歧义调用 VLM；本地无 GPU 时需评估算力方案 |
| **真值缺失** | 主播录像没有游戏内日志 | 用模组自录校验集（阶段 0），这是硬性前置 |

**粗略算力直觉**：30 分钟视频若每 2s 采样 ≈ 900 帧；经稳定帧筛选后战斗相关帧约 200–400。若每帧 1 次小 VLM 调用，1000 小时素材 ≈ 2000 局 ≈ 60–80 万次调用。**这个量级决定了"能用规则/检索解决的绝不用 VLM"不是优化，而是可行性前提。**

---

## 6. 关键选择（已确认，2026-09-14）

| # | 问题 | 结论 |
|---|---|---|
| 1 | 目标游戏 | **杀戮尖塔 2** |
| 2 | 是否含决策理由 | **希望包含**，但按提取难度分档推进（见 §7.5：只做 ASR + 时间对齐，语义归属下推） |
| 3 | 推理算力 | **数据处理走第三方 VLM API**；后续微调等使用自有 GPU 设备 |
| 4 | 首批范围 | **整局**（含地图 / 事件 / 商店） |
| 5 | 精度目标 | **待定**——建议在 M1 校验集建成后，先用它测出基线，再回填可接受阈值 |

---

## 7. 方案定稿（基于已确认选型）

### 7.1 选型确认
| 维度 | 确认结论 | 主要影响 |
|---|---|---|
| 目标游戏 | **杀戮尖塔 2**（Early Access，2026-03-05 上线） | 必须做 **patch 版本化**；UI 会随补丁变动 |
| 覆盖范围 | **整局**（地图 / 战斗 / 事件 / 商店 / 篝火 / 宝箱 / 奖励 / 卡组） | 需要完整的**页面状态机**，而非只做战斗 |
| VLM 推理 | **第三方云端 API** | "调用预算"成为一等工程约束；本地无 GPU 也能跑 |
| 确定性 CV | 本地 CPU（帧差分 / pHash / 模板 / ROI） | 90% 的"筛帧"工作不该花 API 钱 |
| 音频 | ASR（自有 GPU 本地跑或 API） | 决策理由的载体 |
| 后续微调 | 自有 GPU 设备 | 前置任务的产出要**为微调预留数据形态** |

### 7.2 STS2 整局页面状态机（切分骨架）

**页面级（PAGE）**
`RUN_START`（角色/飞升选择）· `MAP` · `COMBAT` · `EVENT` · `SHOP` · `REST`（篝火）· `TREASURE` · `CARD_REWARD` · `RELIC_REWARD` · `POTION_REWARD` · `CARD_SELECT`（移除/升级）· `BOSS_RELIC` · `DECK_VIEW` · `RELIC_VIEW` · `ACT_TRANSITION` · `GAME_OVER` / `VICTORY`

**战斗内子状态（COMBAT_PHASE）**
`TURN_START` → `PLAYER_INPUT`（可交互等待）→ `CARD_DRAG`（出牌动画中）→ `ENEMY_TURN` → `COMBAT_END`

**地图内子状态**
`MAP_VIEW`（可选节点高亮）→ `PATH_HOVER`（悬停预览）→ `NODE_CONFIRM`

**关键设计：用"生成规则"当先验，而不是纯视觉重建路线图。**
STS2 的地图生成是有规则的（列/行/节点类型约束），可参考 [Spire Codex: Map Generation](https://spire-codex.com/pol/mechanics/map-generation)、[灰机 wiki: 房间](https://sts2.huijiwiki.com/wiki/%E6%88%BF%E9%97%B4)、[STS2 Acts](https://sts2.wiki/acts/)。
→ 视觉只负责识别"当前可选节点集合 + 玩家选了哪个"，**整张地图由规则先验补全并校验**。这比逐节点识别可靠得多，也便宜得多。

### 7.3 云端 API 约束下的 8 条工程铁律

1. **调用预算是一等公民。** 每个环节都要回答"这一步能不能不调 API"。
2. **网格拼帧摊销。** 页面分类不需要逐帧调：把 9 帧拼成 3×3 一张图，一次调用判定 9 个时刻的页面类型 → 调用量直接降到 1/9。这是最有效的省钱手段。
3. **ROI 裁剪再提问。** 全帧 ≈ 1000–1600 image token；手牌区/血条/能量 ROI ≈ 100–300 token。**差一个数量级。**
   **但要分场景：** 战斗是"高频小问题"，必须 ROI 化；而事件/商店/奖励界面是"低频大文本"，**整屏一次读完反而更划算**，不要机械地切 ROI。
4. **分级升级（cascade）。** 廉价模型/规则先判 → 只在低置信时升级到强模型，并记录升级原因。
5. **优先走 Batch API。** 主流厂商的异步批处理通常有大幅折扣，且本任务**完全可离线批处理、对延迟零要求**——这是白拿的折扣。
6. **幂等缓存。** 缓存键 = `hash(图像内容) + prompt 版本 + model 版本 + ROI 定义版本`。重跑必须命中缓存，否则调试会烧掉预算。
7. **强约束输出。** 要求 JSON Schema / 结构化输出；拿到后**必须过本地校验**（枚举合法性、类型、ID 存在性），不合格直接重问而不是硬塞进日志。
8. **失败隔离 + 断点续跑。** 单帧失败不能让整局作废；按局/按段可恢复。

**另需入库的元数据**：模型名与版本、prompt 版本、调用时间、token 用量与费用。**没有这个，日志无法复现，也无法做成本归因。**

### 7.4 成本模型（量级，需按当期价目复核）

单局（按 45 分钟计）调用预算目标：

| 环节 | 朴素做法 | 优化后 | 手段 |
|---|---|---|---|
| 页面级切分 | ~900 次 | **~100 次** | 3×3 网格拼帧 + 降分辨率 |
| 战斗状态抽取 | ~400 次 | **~250 次** | ROI + 稳定帧去重 + 规则优先 |
| 地图/商店/事件/奖励 | ~150 次 | **~80 次** | 规则先验 + 只在歧义处调用 |
| 低置信升级 | — | **~50 次** | 强模型兜底 |
| **合计** | **~1500 次** | **~450–500 次** | — |

→ 优化前后的差距是 **3 倍以上**，且随素材量线性放大。以 1000 局（≈750 小时）计，优化后约 **45–50 万次调用**。
具体金额取决于所选模型档位，需按当期价目表核算；参考价格对比：[LLM API 价格对比 2026](https://huntifyai.com/zh-CN/llm-api-pricing?sort=official)、[Best VLMs 2026 (Mixpeek)](https://mixpeek.com/curated-lists/best-vision-language-models)、[LlamaIndex: Best VLMs & Agentic OCR](https://www.llamaindex.ai/insights/best-vision-language-models)。

**模型选型判断维度**（按重要性排序）：① 结构化输出/JSON schema 支持 ② 多图输入（拼帧必需）③ 图像 token 计量与缩放控制 ④ OCR/小字号中文识别能力 ⑤ grounding（坐标）能力 ⑥ 批处理折扣 ⑦ 单价。

### 7.5 音频与"决策理由"：三档难度，建议只做前两档

你提到"包含决策理由会很有帮助，具体视提取难度而定"。我的建议是**按难度切三档，只在前两档投入，第三档下推给下游**：

| 档 | 内容 | 难度 | 建议 |
|---|---|---|---|
| **A** | ASR 全文转写 + 词级时间戳 | **低** | **无条件做**。成本极低，先全量存下来，永不后悔。 |
| **B** | 把 utterance 对齐到决策事件（±2s 窗口 + 说话人分离 + 意图粗分类） | **中** | **做**。这是视频路线的核心增量价值。 |
| **C** | 判定"这句话是否在解释这个决策的理由"，并建立因果归属 | **高**（语义理解 + 反事实推断，易错） | **前置任务只做时间对齐，不做语义归属。** |

**理由**：C 档的正确率永远无法自证，一旦做错会污染训练数据的因果结构，且需要大量人工标注。而**只要有 A+B（"决策时刻 ±2s 的原文"），下游微调模型完全有能力自己学出归属关系**——你已有 GPU，把这件事放到下游更合适。这也契合项目"前置任务"的定位：**前置任务只保证"可追溯的对齐"，不保证"语义归属"。**

### 7.6 修订后的里程碑

| 阶段 | 内容 | 出口标准 |
|---|---|---|
| **M0** 地基 | spire-codex 元数据入库（含 patch 版本）；日志 schema 定稿；yt-dlp 拉取与预处理 | 元数据可按 ID 查询；schema 冻结 v1 |
| **M1** 校验集 | 模组自录 20–50 局（真值日志 + 同步录屏） | 有可量化评测的 ground truth |
| **M2** 切分引擎 | 页面状态机 + ROI 稳定帧检测（纯 CPU，零 API） | 页面切分准确率达标；**不花一分钱 API** |
| **M3** 抽取引擎 | 网格拼帧 + ROI 提问 + 缓存 + 级联升级 + 校验 | 单局 API 调用 ≤ 500 次；字段级准确率达标 |
| **M4** 音频 | ASR + 决策对齐（A+B 档） | commentary 字段带时间戳对齐 |
| **M5** 导出 | JSONL + 置信度分层 + 重放一致性检查 | 重放可复现 HP/能量/牌堆 |
| **M6**（下推） | 用自有 GPU 微调卡面识别器 / 理由对齐分类器 | 归入后续项目 |

---

## 附：参考链接汇总

**尖塔生态**
- Spireeval (ICDMW 2025): https://www.computer.org/csdl/proceedings-article/icdmw/2025/813200c404/2eP1Asezxfi ｜ https://ieeexplore.ieee.org/document/11416128/
- Orak (ICLR 2026): https://proceedings.iclr.cc/paper_files/paper/2026/hash/63506d49e90266a51f21ba8edbd49f46-Abstract-Conference.html
- spire-codex: https://github.com/ptrlrd/spire-codex ｜ https://spire-codex.com/about
- AgenticSTS: https://huggingface.co/datasets/AlayaLab/AgenticSTS-trajectories
- MaT1g3R/Slay-the-Spire-data: https://github.com/MaT1g3R/Slay-the-Spire-data
- STS2 模组（战斗日志/遥测）: https://www.nexusmods.com/slaythespire2/mods/100 ｜ /928 ｜ /479
- STS2 早期访问上线（2026-03-05）: https://spire-codex.com/news/1825093633186167

**方法论（录像 → 结构化动作）**
- SeeAction (ICSE 2025): https://arxiv.org/abs/2503.12873
- GameplayQA (ACL 2026): https://arxiv.org/abs/2603.24329 ｜ https://aclanthology.org/2026.acl-long.1585/
- OmniParser v2: https://github.com/microsoft/OmniParser
- ScreenVLM: https://huggingface.co/docling-project/ScreenVLM
- PaddleOCR-VL: https://github.com/PaddlePaddle/PaddleOCR
- VideoCUA: https://huggingface.co/datasets/ServiceNow/VideoCUA ｜ Video2GUI: https://huggingface.co/papers/2605.14747

**关键帧抽取**
- PySceneDetect: https://www.scenedetect.com/docs/head/api/detectors.html
- Video_Page_Extractor (pHash+SSIM 稳定帧): https://github.com/davidhc1230/Video_Page_Extractor
- video2dataset: https://github.com/iejMac/video2dataset
- LENS (ECCV 2026): https://github.com/zhangce01/LENS
- FOCUS (ICLR 2026): https://proceedings.iclr.cc/paper_files/paper/2026/hash/a010577f93a8301dada61f0b97cda923-Abstract-Conference.html

**音频**
- WhisperX: https://github.com/m-bain/whisperX
