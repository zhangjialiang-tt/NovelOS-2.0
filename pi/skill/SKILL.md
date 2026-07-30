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

## 无合法动作时的边界（Goal 1 守卫）

1. 任何创作文件写入前，必须先调用 `novelos_status` 和 `novelos_next`。
2. 未获得 Core 返回的 `task_id` 与 `staging_path`，不得创建 `work/` 下任何目录或文件。
3. `legal_actions` 为空或 `next` 无 `suggested_action` 时，只能向用户说明功能尚未开放，不得自行模拟任务、自造 task-id 或文件名。
4. 除非用户明确要求开发 Pi Skill，否则不得创建或修改任何 `SKILL.md`。

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
