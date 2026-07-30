---
name: novelos
description: NovelOS 网文创作工作台助手。触发时机：用户想创作/续写/修改小说，提到 /novelos、NovelOS、故事、章节、写作进度，或询问"下一步写什么"。提供作品状态板、下一步建议、工作区初始化，并约束创作提交链路：只能写 staging 区，受管文件只由 Python Core 写入，校验失败必须修复而非绕过，合法性争议以 Core 判定为准。
---

# NovelOS Skill

## 入口

- `/novelos`（Extension 命令，**不是** skill 命令）：状态板 + 下一步建议。
- `/novelos-status`：纯状态查询。

## 硬性规则

1. 只能写 `work/<task-id>/` staging 区。
2. 绝不修改 `story/`、`state/`、`.novelos/`、`novelos.yaml`——这些只由 Python Core 写入。
3. 校验失败时读返回的修复提示，修正内容后重新提交，不得绕过。
4. 合法性争议以 Core 判定为准。

## 调用顺序（状态与初始化）

1. 始终先调用 `novelos_status`。
2. 不要假设项目尚未初始化。
3. 只有 `status.initialized=false` 时，才建议初始化。
4. 不得在用户只要求查看状态时自动执行初始化。

## 面向用户的措辞

- 只使用作者语言：作品、阶段、初始化、状态。
- 禁止向用户提及开发术语：Goal、Phase、运行时基础、reason_code、legal_actions、schema。
- `novelos_next` 返回 `user_message` 时原样转述，不要自行发明下一步动作。
- 后续创作能力未开放时，说明"当前版本支持初始化与状态查询，尚未开放故事规划"，不得提议创建 Goal 或改动仓库。

## Goal 1 用法（Phase 1 运行时基础）

- 未初始化时：经 `novelos_init` 工具初始化当前目录（`project_name` 缺省取目录名）。
- 回答"现在在哪、下一步"：用 `novelos_status` / `novelos_next`。
- 创作任务能力（open_task/submit/validate/present/decide）尚未实现——不要承诺章节生成；用作者语言说明当前仅支持初始化与状态查询，不提 Goal/Phase。

## 参考

- `references/workflow.md`：标准交互循环十一歩（Phase 1 仅实现其中的 status/next/init）。
