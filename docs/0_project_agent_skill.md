# 项目级 agent skill

新增 `.agents/skills/deep-the-spire-project/`，用于要求 Codex 在执行项目工作前读取仓库根目录的 `agent_readme.md`，并持续以该文件的当前内容作为项目级权威指示。

该 skill 不复制 `agent_readme.md` 的具体规则；权威文档仍由原文件维护。
