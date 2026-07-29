# Phase 1 实施计划

源自 `docs/prompt.md` §二 的 Goal 分解。冻结契约见 `docs/phase0/`；条款追踪见 `TRACEABILITY.md`。

## Goal 表

| Goal | 范围 | 状态 |
|---|---|---|
| 00 仓库基线 | README、AGENTS.md、TRACEABILITY.md、PHASE1_PLAN.md、包骨架与 smoke test | 已合入（2026-07-30） |
| 01 bootstrap 纵向链路 | `version/doctor/init/status/next/integrity-scan` 五动词加扫描；Extension `/novelos`、`/novelos-status` 与工具 `novelos_init/novelos_status/novelos_next`；安装脚本；空目录经真实 Extension 与真实 Core 初始化并呈现状态板 | 本分支完成（待演示证据） |
| 02 Premise 闭环 | open_task/submit/validate/present/decide 全链、premise 任务类型、DecisionRef 与 UI 中介确认 | 待启动 |
| 03 一章切片 | chapter_plan + chapter_text 任务、claims 消费与 state 投影、替换集合雏形 | 待启动 |
| 04 替换集合与崩溃恢复 | replacement.targets 原子切换、STALE/锁定事件、崩溃恢复与 reconcile 入口 | 待启动 |
| 05 三章 Pilot | L4 strict-real 三章纵向运行、G0–G3 全门、run_record 与完整性证据 | 待启动 |

## 测试节奏（冻结文档 10 §6）

- 每次提交：L0 + L1 + L3（`uv run pytest -m "l0 or l1 or l3"`）。
- 修改 Skill / Extension / Task Package / 交互协议：触发 L2 smoke。
- PR 合并前或定时：L2 全套。
- 进入 Pilot 前：L0–L3 全套全绿。

## 分支与 PR 规则（docs/prompt.md §五）

- `base/develop` 集成；每 Goal 独立短分支 `goal/NN-*`。
- 每分支以 Draft PR 呈现：覆盖的冻结条款、非目标、运行命令与结果、新增测试、已知问题。
- Goal 1 的完成判据（docs/prompt.md §六）：在空作品目录中，经真实 Extension 与真实 Core 完成 init 并呈现状态板。
