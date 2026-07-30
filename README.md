# NovelOS 2.0

运行在 Pi Agent 上、以本地文件为作品事实源、由 Python 确定性内核保障一致性的交互式网文创作工作台。

## 状态

Phase 1 —— Goal 0/1/2 已合入：

- **Goal 0** 仓库基线；**Goal 1** bootstrap 纵向链路（`version/doctor/init/status/next/integrity-scan` + Extension `/novelos`、`/novelos-status` + 安装脚本）。
- **Goal 2** Premise 完整闭环（Core + Pi 交互）：
  - 六动词 `task open / candidate submit / validate / present / decide / checkpoint`；
  - 进程内原子事务 + 根目录工作区锁 + 双层写前检查（内部损坏拒绝不写事件；受管带外修改写审计事件后拒绝）；
  - 候选 LF 规范化后冻结（preview hash ≡ commit hash）；staging 路径安全（符号链接/路径逃逸拒绝）；
  - PendingDecision 与 DecisionRef 分离存储，nonce 一次性消费；ACCEPT 原子 commit 落盘 `story/premise.md`；REVISE 作者意见逐轮进工作包，重启后 resume 交还原始想法与最新意见；
  - 作者决定**只经 `novelos_decide` 的 TUI 对话框**——模型参数不含决定值；
  - 确定性 L2 合约门（隔离环境 + 分支资产注入 + 脚本化模型）与真实 Pi TUI 十六步演示证据（`docs/evidence/goal-02/`）。
- 尚未开放：故事规划（Goal 3）、一章切片（Goal 4）、替换集合与崩溃恢复（Goal 5）、三章 Strict-Real Pilot（Goal 6）。

## 三层架构

- **Pi** = Agent Runtime（模型交互与 UI）。
- **Extension**（`pi/extension/`）= 薄适配：spawn Core、解析 JSON 信封、渲染 UI，零领域逻辑。
- **Python Core**（`src/novelos/`）= 确定性状态、校验、事务、文件治理；受管文件（`story/`、`state/`、`novelos.yaml`、`.novelos/`）的唯一写入者。Agent 只写 `work/<task-id>/` staging 区。

权威契约为 `docs/phase0/` 十份冻结文档；条款—实现—测试追踪见 `docs/implementation/TRACEABILITY.md`。

## 仓库布局

```text
docs/phase0/            十份冻结文档，权威契约
docs/implementation/    PHASE1_PLAN.md / TRACEABILITY.md
docs/evidence/          演示验收证据（脱敏）
src/novelos/            Python 确定性内核（Core）
tests/                  L0/L1/L3 测试（含 fixtures）
pi/extension/           Pi Extension（薄适配层）
pi/skill/               Pi Skill（创作循环规则）
pi/l2/                  L2 合约测试基建（隔离 agentDir + 分支资产注入 + faux 脚本化模型）
scripts/                安装与诊断脚本
```

## 快速开始

前置：Python ≥3.11、uv、Node ≥22.6（测试需 TS type-stripping）、已安装的 `pi`。

```bash
python scripts/install.py
cd <空作品目录> && pi
```

在 pi 中：

1. `/novelos` 查看状态板与下一步建议；
2. 告诉 pi 你的故事想法——`legal_actions` 含 `premise` 时，Agent 经 `novelos_open_task` 开任务，读取工作包说明，只在 `work/<task-id>/` 内写候选（premise = `premise.md`）；
3. `novelos_submit_candidate → novelos_validate`，校验失败按修复提示静默修改重交；
4. `novelos_present` 后在 TUI 对话框中做作者决定：ACCEPT（保存为正式版本）/ REVISE（补充意见后重写）/ REJECT（丢弃草稿）；
5. ACCEPT 正式落盘 `story/premise.md`；REVISE 的意见进入下一轮工作包；`novelos_checkpoint` 保存进度。重启后 `/novelos` 与 `task open` 自动恢复任务坐标。

## 开发

```bash
# 每提交节奏（冻结文档 10 §6）
uv sync && uv run pytest -m "l0 or l1 or l3"
node --test "pi/extension/test/*.test.ts"

# L2 合约门（脚本化模型、隔离环境、分支资产注入；合并前必跑）
NOVELOS_L2=1 node --test "pi/l2/test/*.test.ts"

# L2 live smoke（真实模型、已安装资产；仅证据，不作合并门）
NOVELOS_L2_LIVE=1 node --test "pi/l2/test/live-smoke.test.ts"
```

Core CLI 动词：`version / doctor / init / status / next / integrity-scan / task open / candidate submit / validate / present / decide / checkpoint`，均支持 `--json`（单信封）与 `--workspace`。变更动词经 `--request-id` 幂等重放（`decide` 为一次性命令，不经重放；重复 nonce 返回 `DECISION_NONCE_CONSUMED`）。`--source-mode DETERMINISTIC_FIXTURE` 与 `decide --fixture` 仅限 evaluation 运行（`NOVELOS_RUN_MODE=evaluation`）。

## 文档索引

- 冻结文档索引表：`docs/phase0/01-PRODUCT_DEFINITION.md` §13
- 条款—实现—测试追踪：`docs/implementation/TRACEABILITY.md`
- 阶段计划与 Goal 分解：`docs/implementation/PHASE1_PLAN.md`
- Goal 2 演示验收证据：`docs/evidence/goal-02/`
