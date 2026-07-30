# 追踪矩阵：冻结条款 → 实现 → 测试

四列：冻结条款 | 实现位置 | 测试位置 | 状态。Goal 1（bootstrap 纵向链路）覆盖行如下；
其余条款随后续 Goal 落地。

| 冻结条款 | 实现位置 | 测试位置 | 状态 |
|---|---|---|---|
| 04 §1.2 版本握手 | `src/novelos/cli.py`（version）、`pi/extension/core-client.ts` | `tests/test_l1_cli.py::TestVersion`、`pi/extension/test/core-client.test.ts` | DONE |
| 04 §1.3 JSON 信封 / §1.4 退出码 | `src/novelos/protocol.py`、`src/novelos/cli.py` | `tests/test_l1_cli.py::TestEnvelope` | DONE |
| 04 §1.5 --request-id 幂等（init 范围） | `src/novelos/workspace.py`（request ledger） | `tests/test_l0_requests.py` | DONE |
| 04 §2 init/status/next 工具 | `src/novelos/cli.py`、`pi/extension/tools.ts` | `tests/test_l1_cli.py`、`tests/test_l3_bootstrap.py` | DONE |
| 04 §4 错误码（Goal 1 子集）/ §5 CLI 动词 | `src/novelos/protocol.py`、`src/novelos/cli.py` | `tests/test_l1_cli.py::TestExitCodes` | DONE |
| 04 §1.1 launcher 发现（r6 回写） | `pi/extension/core-client.ts`、`scripts/install.py` | `pi/extension/test/core-client.test.ts`、`tests/test_l1_install.py` | DONE |
| 05 §2 状态板 / §6 错误转译 / §7 schema 规避 | `pi/extension/ui.ts`、`pi/extension/commands.ts` | `pi/extension/test/ui.test.ts` + 真实 Pi 演示 | DONE |
| 06 §1 Workspace 布局 / §3 hash 账本 | `src/novelos/workspace.py` | `tests/test_l0_workspace.py` | DONE |
| 06 §3.1 双层完整性 / §3.2 hash 基线 | `src/novelos/integrity.py` | `tests/test_l0_integrity.py`、`tests/test_l1_cli.py::TestInitThenScan / ::TestTamperScan` | DONE |
| 06 §6 事件 schema + 锚定不变量 | `src/novelos/events.py` | `tests/test_l0_events.py`、`tests/test_l1_cli.py::TestInitThenScan` | DONE |
| 02 §4.2 诊断三层 | `scripts/install.py`、`src/novelos/cli.py`（doctor）、`pi/extension/index.ts` | `tests/test_l1_install.py`、`tests/test_l1_cli.py::TestDoctor`、`pi/extension/test/core-client.test.ts` | DONE |
| 10 §2 L0/L1/L3 执行器 / §6 节奏 | `pyproject.toml`、`tests/` | `uv run pytest -m "l0 or l1 or l3"` | DONE |
| 07 §2 task.json / §3 包结构 / §5 premise output / §6 instructions / §7 capability / §8 生命周期（open-or-resume、REVISE 逐轮意见） | `src/novelos/tasks.py` | `tests/test_l0_tasks.py`、`tests/test_l1_taskflow.py` | DONE |
| 06 §3 写前扫描（双层）/ §3.1 内部层损坏拒绝 / 进程内原子事务 / 工作区锁 | `src/novelos/transaction.py`、`src/novelos/integrity.py` | `tests/test_l0_transaction.py`、`tests/test_l0_preflight.py`、`tests/test_l1_taskflow.py` | DONE |
| 06 §4 Candidate 存储 / §3.2 LF 规范化 hash 基线 | `src/novelos/candidates.py` | `tests/test_l0_candidate.py` | DONE |
| 06 §6 事件锚定 / §6.1 DecisionRef（Pending 分离、nonce 恒消费、fixture 内部消费） | `src/novelos/decisions.py` | `tests/test_l0_decision.py` | DONE |
| 04 §3.5/§3.6 present/decide 语义（TOCTOU、一次性、fixture 分支）/ §4 新错误码（r7） | `src/novelos/decisions.py`、`src/novelos/cli.py`、`src/novelos/protocol.py` | `tests/test_l0_decision.py`、`tests/test_l1_taskflow.py` | DONE |
| 06 §2 ArtifactRevision 登记 / §9 checkpoint（最小，无 run） | `src/novelos/checkpoints.py` | `tests/test_l0_checkpoint.py` | DONE |
| 08 §6 任务级度量（Core 可知字段 + token null） | `src/novelos/checkpoints.py`、`src/novelos/tasks.py`、`src/novelos/candidates.py` | `tests/test_l0_checkpoint.py` | DONE |
| 03 §4 G0 负向（Goal 2 子集） | `tests/` | `tests/test_l0_decision.py`、`tests/test_l0_transaction.py` | DONE |
| 02 §7.3/§7.6/§9 UI 中介与确认守卫（ctx.mode==="tui"） | `pi/extension/tools.ts` | `pi/extension/test/tools-defs.test.ts` + 真实 Pi 演示 | DONE |
| 01 §7 决定哲学 / 05 §3 guided 序列 / §5 确认节点 / §8 无 UI 模式 | `pi/extension/tools.ts`、`pi/skill/SKILL.md` | `pi/l2/test/premise.test.ts`、真实 Pi 演示 | DONE |
| 02 §10 L2 行为契约 / 10 §2 L2 执行器（确定性合约 + live smoke 分级） | `pi/l2/` | `pi/l2/test/*.test.ts` | DONE |
| A 守卫规则 | `pi/skill/SKILL.md` | `pi/l2/test/guard.test.ts`（合约）+ live smoke（证据） | DONE |
| 04 §1.1 launcher 发现（r6/r7：故障分类 NOT_FOUND vs 协议错误 + DI 测试面） | `pi/extension/core-client.ts` | `pi/extension/test/core-client.test.ts` | DONE |
