# Phase 1 实施计划

源自 `docs/prompt.md` §二 的 Goal 分解。冻结契约见 `docs/phase0/`；条款追踪见 `TRACEABILITY.md`。

## Goal 表

| Goal | 范围 | 状态 |
|---|---|---|
| 00 仓库基线 | README、AGENTS.md、TRACEABILITY.md、PHASE1_PLAN.md、包骨架与 smoke test | 已合入（2026-07-30） |
| 01 bootstrap 纵向链路 | `version/doctor/init/status/next/integrity-scan` 五动词加扫描；Extension `/novelos`、`/novelos-status` 与三工具；安装脚本 | 已合入（2026-07-30，PR #1） |
| 02 Premise 完整闭环 | Task/Candidate/PendingDecision/DecisionRef/ArtifactRevision/Checkpoint；`task open / candidate submit / validate / present / decide / checkpoint` 六动词；premise output contract；Extension 六工具（decide UI 中介）；确定性 L2 | 已合入（2026-07-30，PR #2 / #3 / #4） |
| 03 Story Plan 完整闭环 | `story_plan` 任务类型（输入 story/premise.md 当前版本，07 §4.1）、STORY_PLAN artifact、premise→plan 依赖与 STALE_INPUT 实装 | 不再实施（2026-07-30 项目关闭，见 PROJECT_CLOSURE.md） |
| 04 一章切片 | `chapter_plan` + `chapter_text` 任务、claims.yaml 消费与 state 投影（06 §5）、替换集合雏形 | 不再实施（2026-07-30 项目关闭，见 PROJECT_CLOSURE.md） |
| 05 替换集合与崩溃恢复 | `replacement.targets[]` 两阶段原子切换（02 §7.5 / 03 §5 钉死场景）、STALE/锁定事件、**事务 journal 崩溃 reconcile（含 OS 级文件锁升级 msvcrt/fcntl）**、`export` 动词 | 不再实施（2026-07-30 项目关闭，见 PROJECT_CLOSURE.md） |
| 06 三章 Strict-Real Pilot | L4 strict-real 三章纵向运行、G0–G3 全门、**run 生命周期（start/finish）与 run_token_summary**、request ledger 清理 | 不再实施（2026-07-30 项目关闭，见 PROJECT_CLOSURE.md） |

## 测试节奏（冻结文档 10 §6）

- 每次提交：L0 + L1 + L3（`uv run pytest -m "l0 or l1 or l3"`）。
- L2 合约（脚本化模型、隔离环境、分支资产注入）：Skill/Extension/协议变更必跑；合并前必跑——是合并门。
- L2 live smoke（真实模型、已安装资产）：仅证据，不作合并门。
- 进入 Pilot 前：L0–L3 全套全绿。

## 分支与 PR 规则（docs/prompt.md §五）

- `base/develop` 集成；每 Goal 独立短分支 `goal/NN-*`。
- 每分支以 Draft PR 呈现：覆盖的冻结条款、非目标、运行命令与结果、新增测试、已知问题。
- Goal 1 的完成判据（docs/prompt.md §六）：在空作品目录中，经真实 Extension 与真实 Core 完成 init 并呈现状态板。
- Goal 2 完成判据：空目录经真实 Extension/Agent 走完 open_task→submit→validate→present→（UI）decide（含 REVISE→rev-2）→checkpoint，重启恢复正确，story/premise.md 落盘且 integrity-scan PASS。
