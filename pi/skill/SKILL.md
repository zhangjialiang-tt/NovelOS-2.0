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

## 用法（Phase 1 运行时基础 + Goal 2 Premise 闭环）

- 未初始化时：经 `novelos_init` 工具初始化当前目录（`project_name` 缺省取目录名）。
- 回答"现在在哪、下一步"：用 `novelos_status` / `novelos_next`。
- 故事核心（premise）创作循环已开放；故事规划与章节尚未实现——不要承诺章节生成；用作者语言说明，不提 Goal/Phase。

## 创作循环（premise）

1. 先查询合法动作：`novelos_status` / `novelos_next`；仅当 `legal_actions` 含 `premise` 或 `next` 建议 `open_task/continue_task` 才开任务。
2. `novelos_open_task(task_type="premise", brief=<用户故事想法摘要>)`——**创建时 brief 必填**，先在对话中收集作者想法；返回 `resumed: true` 时是恢复既有任务（无需再给 brief；`original_brief` 告诉你在继续什么，`revision_guidance_ref` 是最新作者意见）。`task_id`/`staging_path` 只取自返回值，绝不自行构造。
3. 读取 `instructions_ref` 指向的工作包说明；REVISE 轮次必须重读最新 revision-note（作者意见逐轮存于 context/revision-notes/）。
4. 只在 `staging_path` 内写 `allowed_outputs`（premise = `premise.md`）。
5. `novelos_submit_candidate` → `novelos_validate`；失败按 errors 的 hint 修改后重新 submit + validate（静默修复 ≤3 轮，超出向用户说明；不展示错误码、字段名、内部路径）。
6. 校验通过后 `novelos_present`；作者决定（ACCEPT/REVISE/REJECT）**只能经 `novelos_decide` 的 UI 对话框**——模型参数不含决定值，不得代为选择。
7. ACCEPT 落盘后用作者语言报喜；REVISE 取回作者意见（工具结果含原文与意见文件路径）→ 回第 3 步重读后生成新候选；REJECT 终止。
8. 有进展后 `novelos_checkpoint` 保存进度。

## 参考

- `references/workflow.md`：标准交互循环十一步（status/next/init 与 premise 循环已实现）。
- Phase 注记：status/next/init 与 premise 创作循环已实现；故事规划（story_plan）起随后续 Goal 落地。
