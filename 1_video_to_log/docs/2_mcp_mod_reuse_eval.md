# 第 2 步：STS2 MCP 模组复用评估

> 评估日期：2026-09-17  
> 评估对象：`1_video_to_log/temp/sts2-mcp`  及其公开上游 `Yidhar/sts2-mcp`  
> 对照规范：`1_video_to_log/human_guidelines/0_combat_log_format.md`、`2_mcp_mod_reuse_eval.md`

## 结论

**建议有条件复用。** 可以复用该项目的 STS2 游戏桥接、合法动作发现、动作执行、状态版本控制和部分高层 resolver；不建议把当前仓库原样作为本项目训练和实战的最终接口。

复用边界应当是：

- 保留桥接模组和 MCP server 的底层通信与动作执行能力；
- 在其上增加面向本项目日志格式的适配层；
- 补齐按需查看地图、牌组和战斗牌堆的语义接口；
- 明确隐藏信息边界，禁止工具响应把模型不应知道的随机顺序或内部字段泄露给训练数据；
- 让离线日志回放和在线实战共用同一份工具 schema、状态摘要和错误语义。

若不接受上述适配工作，则结论为“不应直接复用”。

## 查证范围和证据

本次评估检查了临时仓库的 README、变更记录、Node MCP server、C# bridge 源码、工具 profile、smoke test 和本地 Git 历史，并通过 GitHub API 核对公开上游状态。

截至 2026-09-17，公开上游 `Yidhar/sts2-mcp` 的 HEAD 为提交 `697f595cd459211012fc4cc6610dfa64a8c96ee4`，提交信息为 `release: v0.7.12`，提交日期为 2026-03-22。临时仓库的 MCP server 常量为 `0.4.20`；本地仓库本身未出现未提交修改。上游信息用于确认项目仍在演进，不能替代对本地锁定版本的测试。

已完成的可重复检查：

1. `node --check packages/mcp-server/index.js` 通过。
2. 使用隔离 fixture 对 `debug`、`minimal`、`strategic` 三个 profile 检查工具暴露和状态摘要。
3. fixture 验证表明 combat 状态摘要默认只保留抽牌堆前三张（`draw_top`），不会把第四张继续输出；牌组和地图查询分别走独立函数。
4. 地图未打开时，路线查询返回 `map_not_open`；地图打开后能生成未来节点路线树，并附带 run-aware 路线字段。
5. MCP `initialize`、`tools/list` 通过。`strategic` profile 暴露 25 个工具，server 报告版本 `0.4.20`、协议版本 `2025-03-26`。
6. 在不存在游戏 bridge session 的隔离路径上运行 smoke test，`get_bridge_status`、`get_state`、`list_actions` 均按预期返回 `session_file_missing`，没有误认为游戏已连接。

尚未完成的验证：真实 STS2 进程、真实 mod DLL、真实事件/战斗/商店流程和跨版本兼容性。因此本文不宣称已证明实机可用。

## 一、是否满足阻塞事件和异步查询

### 能满足的部分

MCP 暴露了两类行为，能够映射到战斗日志中的 `demand` 与 `action`：

| 日志概念 | MCP 对应能力 | 适配判断 |
| --- | --- | --- |
| 阻塞要求，必须处理才能继续 | `sts2_list_actions` 返回当前合法动作；`sts2_perform_action`、`sts2_pick_option`、`sts2_resolve_*`、`sts2_travel_to_coordinate` 执行动作 | 可以映射 |
| 可选观察动作 | `sts2_get_state`、`sts2_get_deck`、`sts2_get_map_routes`、知识查询工具 | 可以映射，但要限制返回信息 |
| 动作后的世界反馈 | 工具结果中的 `state` / `state_after`、`screen_after`、`state_version_after` | 可以映射 |
| 等待游戏状态变化 | `sts2_wait_for_change`、`sts2_wait_until_actionable` | 可以映射为异步等待事件 |
| 过时动作或并发冲突 | `expected_state_version`、`state_version_conflict`、`action_not_available` | 应保留为数据集中的失败反馈 |

桥接层在执行动作前读取 frontier，并可用 `expected_state_version` 检查状态是否仍然匹配；动作执行后还会等待状态稳定。这为日志中的“动作—响应”关联提供了可靠基础。`state_version` 应写入每条 world response，不能只依赖视频时间戳。

### 不能直接满足的部分

当前 MCP 的响应是面向在线 agent 的压缩摘要，不是 `0_combat_log_format.md` 规定的统一事件流。它不会自动生成：

- `id`、`by`、`type`、`to` 等日志字段；
- 人类玩家的 reasoning；
- 视频时间、关键帧和 VLM 证据；
- 阻塞与异步的统一标签；
- 可用于回放的完整工具调用序列。

因此，战斗日志可以转换成“看起来像模型使用该 MCP 的 session”，但必须增加一个确定性的 log-to-session 转换器。转换器应把每一个视频中识别出的玩家观察、玩家动作、世界变化分别编码为 tool call / tool result，并保存 `observed_at`、`source_frame`、`confidence` 和 `state_version`。

推荐的转换关系如下：

```text
world demand       -> tool result / required_action=true
player reasoning   -> assistant message（视频中确实可听见或可读出的内容才写入）
player action      -> assistant tool_call
world response     -> tool result + normalized state snapshot
optional inspection-> assistant tool_call，随后 tool result；没有观察动作就不要补写
invalid/ambiguous  -> tool result error，保留原因和证据，不猜测动作
```

视频无法观察到的内部状态不得由 MCP 事后补写进训练样本，否则会造成训练时的信息泄露。

## 二、地图、牌组和牌堆查询能力

### 已提供能力

`strategic` 和 `debug` profile 有 `sts2_get_deck` 与 `sts2_get_map_routes`。牌组查询是独立的低频策略视图，适合映射 `show_deck`。地图查询可输出当前可达的未来路线节点，适合映射 `show_map`。`minimal` profile 不暴露这两个工具，因此本项目不能使用 minimal profile 作为最终训练/实战 profile。

桥接源码能够识别地图屏幕、地图点和合法 `map:col,row` 动作，也能识别战斗中的 `play_card` 等动作。高层工具还提供牌序列、混合战斗序列、奖励、休息处、卡牌选择、商店和等待状态变化的封装。

### 重要限制

1. **地图查询依赖地图已经打开。** 源码的路线函数在地图屏幕未打开时返回 `map_not_open`；当前动作集合没有发现一个通用的“打开/关闭地图”观察动作。若游戏 UI 本身允许打开地图，需要增加低侵入的 `sts2_show_map`/`sts2_hide_map` 或 `sts2_inspect_map`；否则只能在地图已经可见的时刻查询。
2. **地图工具不是纯观察。** 描述中包含路线偏好和策略建议，例如偏好商店、火堆，降低精英优先级。训练接口应返回客观地图状态，把建议移到可选知识工具或完全移除，避免工具替模型做决策。
3. **牌组是独立查询，牌堆不是完整独立查询。** 当前状态摘要会保留 `draw_top` 等有限字段。需要明确“玩家可见手牌”和“不可见抽牌顺序”的边界；不能把完整随机牌堆顺序作为在线或视频训练输入。
4. **卡牌动作引用不应依赖易变数组下标。** bridge 使用运行时卡牌引用，server 的 sequence 工具会在每次结算后重新匹配手牌，这对在线稳定性有帮助；日志适配层仍应保存稳定的 `selection_id`/卡牌描述和当时的状态版本。

### 推荐的低侵入补全

优先在 MCP server 增加语义包装，而不是修改游戏内部逻辑：

- `sts2_inspect_map`：在合法 UI 时机打开地图，返回客观路线数据，调用方显式关闭或由状态变化自动恢复；
- `sts2_inspect_deck`：统一牌组字段、计数、升级态和当前可见性；
- `sts2_inspect_piles`：只返回模型在该时刻依法可见的手牌、弃牌堆、消耗牌堆和抽牌堆摘要；
- `sts2_get_observation`：按 `scope` 请求单个观察，避免 `get_state` 默认塞入大量信息；
- 统一 `visibility`、`source`、`state_version` 字段，供离线日志和在线响应共用。

如果打开地图需要直接调用游戏 UI 节点，则应在 bridge 中增加一个最小动作，并为它增加状态版本和失败响应；不应通过修改游戏随机或战斗规则实现。

## 三、其它障碍和注意事项

### 1. 训练和实战必须锁定同一接口版本

MCP 当前包含 `minimal`、`strategic`、`debug` 三个 profile，工具数量和返回摘要不同。训练数据必须记录 `profile`、MCP server 版本、bridge schema version、工具 schema hash 和游戏版本。实战加载相同版本组合，否则会出现模型调用不存在的工具或依赖训练中没有的字段。

### 2. 策略知识与游戏观察应分离

server 内置 route planning、deck building、combat tips 等 knowledge 工具。它们可以作为研究辅助，但如果训练样本目标是学习主播的隐性决策，就不应把工具内置建议伪装成游戏世界反馈。建议将知识工具从第一版训练 profile 移除，或把其调用明确标记为外部知识来源。

### 3. 高层批量工具会改变人类动作粒度

`sts2_play_card_sequence`、`sts2_execute_combat_sequence`、`sts2_resolve_shop_visit` 等工具适合稳定在线控制，却可能把多个真实决策压缩为一次 tool call。视频日志若能识别逐张出牌，就应按逐步动作记录；只有视频也确实表现为一次不可分解的选择时才使用批量工具。训练 profile 和实战 profile 应对批量工具的使用规则保持一致。

### 4. 失败、等待和重试必须进入数据集

动作状态冲突、不可用动作、bridge 断线、超时和游戏页面切换都是实际交互的一部分。日志转换器不应静默删除这些事件；应保存可重放的错误结果，并区分模型错误、观察不完整和环境故障。

### 5. 事件顺序和状态稳定性

MCP server 会对动作后状态做 settle，并提供事件流/等待工具。数据集转换时要使用 settle 后的快照作为动作结果，避免把动画中间帧误当作新状态。对 end turn、奖励、商店和地图切换应使用状态版本或明确屏幕变化作为边界。

### 6. 安全和可维护性

bridge 使用本机 HTTP endpoint 和 session token。生产实战应限制 endpoint 暴露范围，并将 token 放在运行时配置中；训练工具不应把 token、绝对路径或调试日志写入样本。上游仍在快速演进，必须锁定 commit/release，保留本地 smoke test 和 schema diff。

### 7. 许可证

临时仓库包含 MIT `LICENSE`。复用时保留版权和许可文本，并在项目文档中记录所锁定的上游 commit。许可证允许修改和再分发，但不代表游戏本体或第三方资产获得授权。

## 四、建议的数据集事件格式

在现有日志格式基础上，建议增加以下字段：

```json
{"id": 42, "by": "player", "type": "action", "action": {"tool": "sts2_inspect_deck", "arguments": {}}, "state_version": 18, "source_frame": "frame_001234.png", "confidence": 0.98}
{"id": 43, "by": "world", "type": "response", "to": 42, "state_version": 18, "visibility": "player_visible", "info": {"deck": "..."}, "source_frame": "frame_001240.png"}
{"id": 44, "by": "world", "type": "demand", "required_action": true, "screen": "card_reward", "options": ["..."], "state_version": 19}
```

必须保留原始视频证据与规范化字段的关系；不要因为工具返回结构更完整，就删除 VLM 置信度、证据帧或不确定性。

## 五、复用决策与实施顺序

### 决策

**复用底层，不原样复用接口。** 这条路线能显著减少游戏接入、动作合法性和状态同步工作量，并且可以让最终模型真实调用同一套 MCP 风格工具。它不能直接解决视频到日志，也不能自动保证人类可见信息边界。

### 实施顺序

1. 锁定临时仓库对应 commit，保存上游版本、bridge schema 和工具 schema 快照。
2. 用真实 STS2 安装启动 bridge，完成最小实机矩阵：新局、地图、事件、普通战、奖励、休息、商店、牌组查看、战斗中查看牌堆、死亡/胜利。
3. 实现观察适配层和 `demand/action/response` 事件转换器。
4. 增加地图开关及牌堆可见性控制；移除或隔离路线策略建议。
5. 为离线日志回放实现同一 MCP tool schema 的 fake bridge，确保训练样本可重放。
6. 用带真值的同步录像与 bridge 日志对齐，评估遗漏、误识别、时间边界和信息泄露。
7. 只有实机矩阵和信息边界测试通过后，才把该 MCP 作为成品模型的实际控制接口。

## 六、实机验收标准

在真实游戏环境中，至少应逐项通过：

- 每个阻塞屏幕都有且只有一组合法推进动作；
- `state_version` 在每次状态变化时单调变化，过时动作得到可解释错误；
- 地图、牌组、手牌、弃牌堆和消耗牌堆查询只返回当时允许模型看到的信息；
- 查看地图/牌组不会推进回合、改变随机数或改变奖励；
- 逐张出牌、结束回合、奖励选择和商店购买可以被完整记录并回放；
- 动画中间状态不会生成重复 world response；
- bridge 断开、游戏重启和页面切换能被明确标记；
- 训练回放工具与实战工具的 schema、错误码和可见性规则一致。

## 最终判断

该项目适合作为 **STS2 接入层和动作执行基础设施**。它目前不适合作为本项目无需改造的“训练环境协议”。完成上述适配、信息边界控制和真实游戏验收后，可以正式复用；在此之前，复用范围应限定为临时开发和底层技术验证。
