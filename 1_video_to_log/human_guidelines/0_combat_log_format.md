本步的目的是从视频中提取包含必要信息的战斗日志, 其必须先有一个统一的结构.  
该结构应尽可能适合LLM会话的输入输出模式.

其形态可能类似:
```jsonl
{"id": 0, "by": "world", "type": "info", "message": "Run started."}
{"id": 1, "by": "world", "type": "demand", "message": "Choose an ancient relic.", "options": ["Neow's fury", "Neow's bones"]}
{"id": 2, "by": "player", "type": "reasoning", "message": "家人们, 我先看一眼地图再抓"}
{"id": 3, "by": "player", "type": "action", "action": "show_map"}
{"id": 4, "by": "world", "type": "response", "to": 3, "info": [
        {"level": 0, "rooms": {
                {"seq": 0, "type": "ancient(current)", "paths": [0, 1, 2]}
            }
        },
        {"level": 1, "rooms": {
                {"seq": 0, "type": "common_combat", "paths": [0]},
                {"seq": 1, "type": "common_combat", "paths": [0, 1]},
                {"seq": 2, "type": "common_combat", "paths": [2, 3]}
            }
        },
        ... ...
    ]
}
{"id": 5, "by": "player", "type": "reasoning", "message": "火堆多可以冲精英啊家人们"}
{"id": 6, "by": "player", "type": "proceed", "to": 1, "choice": "Neow's bones"}
{"id": 7, "by": "world", "type": "demand", "message": "Choose your next room.", "options": ["0_common_combat", "1_common_combat", "2_common_combat"]}
{"id": 8, "by": "player", "type": "reasoning", "message": "看一眼卡组"}
{"id": 9, "by": "player", "type": "action", "action": "show_deck"}
{"id": 10, "by": "world", "type": "response", "to": 9, "info": [
        {"amount": 4, "name": "Strike", "type": "attack", "description": "Deal 6 damage"},
        {"amount": 1, "name": "Strike+", "type": "attack", "description": "Deal 9 damage"},
        {"amount": 4, "name": "Defend", "type": "skill", "description": "Gain 5 block"},
        {"amount": 1, "name": "Bash+", "type": "attack", "description": "Deal 10 damage, apply 3 vulnerable"}
    ]
}
{"id": 11, "by": "player", "type": "reasoning", "message": "走左边冲精英了"}
{"id": 12, "by": "player", "type": "proceed", "to": 7, "choice": "0_common_combat"}
... ...
```
注意这只是一段伪代码形式的范例. 实际上需要的信息可能更多(如完整的地图路线, 卡牌的稀有度和耗能, 角色生命值等), 具体格式也可能不同.

其中, `demand`代表该要求是阻塞的, 玩家必须采取行动`proceed`才能继续. `action`则是玩家可以自主采取的行动, 如查看地图等, 在战斗中还可以查看抽牌堆弃牌堆等.  
在实际的LLM工作中, 这些战斗日志应当易于转化为标准的function calling结构, 以便训练和使用.

在本阶段的工作中, 首次开始涉及战斗日志格式时, 应当基于该标准作进一步细化, 并以文档形式记录.  
后续的工作应当采用最新的格式. 如果再发现规范需要补充拓展, 也应当明确地记录修改.