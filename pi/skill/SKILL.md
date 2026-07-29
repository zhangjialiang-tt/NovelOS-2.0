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

## Goal 1 用法（Phase 1 运行时基础）

- 未初始化时：经 `novelos_init` 工具初始化当前目录（`project_name` 缺省取目录名）。
- 回答"现在在哪、下一步"：用 `novelos_status` / `novelos_next`。
- 创作任务能力（open_task/submit/validate/present/decide）尚未实现——不要承诺章节生成；引导用户等待后续 Goal。

## 参考

- `references/workflow.md`：标准交互循环十一歩（Phase 1 仅实现其中的 status/next/init）。
