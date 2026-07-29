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
