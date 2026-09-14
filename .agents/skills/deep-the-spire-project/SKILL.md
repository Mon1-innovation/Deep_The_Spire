---
name: deep-the-spire-project
description: "Apply the repository's agent_readme.md as the authoritative project guidance before and during any work in Deep The Spire."
---

# Deep The Spire Project

Before taking any project action, read `agent_readme.md` from the repository root using its current contents. Treat that document as the authoritative source for project scope, workflow, file placement, documentation, and interaction requirements. Follow its instructions throughout the task; reread it when the task spans a substantial context change or the file may have changed.

Do not modify, replace, or silently reinterpret `agent_readme.md`. This skill is only a pointer to that document and must not duplicate or summarize its rules, since the document may be revised independently.

If another project-local instruction or the user's request conflicts with `agent_readme.md`, identify the specific conflict clearly and ask the user which direction to take before performing the conflicting work. Do not resolve the conflict by guessing. System and developer instructions still take precedence over this project guidance.

If the file is missing, unreadable, or ambiguous for the requested action, pause project-specific work and report the exact limitation. Keep any safe, unrelated inspection separate from decisions that depend on the document.
