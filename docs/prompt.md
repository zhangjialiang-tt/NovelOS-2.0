## 总体判断

现在应当从“持续设计评审”切换到“受冻结契约约束的纵向实现”。

当前 `base/develop` 分支中，我只能确认根 `README.md` 仍是占位内容 `# novel-master`；尚未确认冻结文档和工程骨架已经入库。 因此建议将该分支视为**实现基线分支**，先完成文档基线和最小工程骨架，再开始业务实现。

实现策略必须坚持三点：

1. 不从 1.0 搬代码搭框架，而是按 2.0 接口重新实现；
2. 不先横向实现所有领域模块，而是每一步都形成真实纵向链路；
3. Pi 承担 Agent Runtime，Python Core 只承担确定性状态、校验、事务和文件治理。

---

# 一、进入编码前的最后收口

上一轮终审仍有几个字段级补丁，建议先落入冻结文档：

- 06 增加 `TASK_OPENED`、`DECISION_PENDING_OPENED` 事件；
- 04/05 将预览身份区分为 `artifact_id + base_artifact_ref`，支持首次创建产物；
- 07 把 `target_artifact_ref` 统一描述为“主目标”；
- `allowed_outputs` 改为 POSIX 相对路径集合；
- `artifact_change` context 按 `replacement.targets[]` 多目标编译；
- 10 增加 `task open`、`present` 后立即执行完整性扫描的测试。

完成后将 04–08、10 标记为冻结，不再进行开放式架构评审。后续设计变化必须通过 ADR 或明确的冻结文档修订。

---

# 二、推荐的实现路线

不要按“Core 全部写完 → Extension 全部写完 → 最后 E2E”的方式实施。建议拆成六个纵向 Goal。

## Goal 0：仓库基线与契约入库

### 产物

```text
NovelOS-2.0/
├─ README.md
├─ AGENTS.md
├─ pyproject.toml
├─ docs/
│  ├─ frozen/
│  │  ├─ 01-PRODUCT_DEFINITION.md
│  │  ├─ ...
│  │  └─ 10-TEST_STRATEGY.md
│  └─ implementation/
│     ├─ PHASE1_PLAN.md
│     └─ TRACEABILITY.md
├─ src/novelos/
└─ tests/
```

`TRACEABILITY.md` 只需要四列：

| 冻结条款          | 实现位置 | 测试位置 | 状态 |
| ----------------- | -------- | -------- | ---- |
| 04 §1.3 JSON 信封 | 待实现   | 待实现   | TODO |
| 06 §3 双层完整性  | 待实现   | 待实现   | TODO |

### 验收条件

- 十份文档版本和索引一致；
- README 不再使用 `novel-master` 名称；
- `AGENTS.md` 明确：冻结文档为权威、Agent 只能写 staging、禁止自行修改契约；
- 最小测试命令可以运行，即使暂时只有空测试。

---

## Goal 1：Bootstrap 真实纵向链路

首个 Goal 不只是创建 Python 包，而是打通：

```text
Pi
→ NovelOS Extension
→ Python Core launcher
→ 空目录初始化
→ 状态板
```

### 实现范围

Core：

- `version`
- `doctor`
- `init`
- `status`
- `next`
- JSON 信封
- 退出码
- `INITIALIZED` 事件
- 最小 Workspace
- hash ledger 与 internal manifest 的初始版本

Extension：

- launcher 发现和版本握手；
- `/novelos`；
- `/novelos-status`；
- `novelos_init`；
- `novelos_status`；
- `novelos_next`。

### 验收场景

```text
进入空目录
→ 打开 Pi
→ /novelos
→ 提示尚未初始化
→ 自然语言要求开始新故事
→ novelos_init
→ 再次 /novelos
→ 展示当前阶段和下一步
```

必须通过真实 Extension 调用 Core，不能只用 Python 测试模拟。

这是第一次“产品存在性”验证。

---

## Goal 2：Premise 单任务闭环

只支持 `premise`，但完整实现统一循环：

```text
open_task
→ Agent 写 work/<task-id>/
→ submit_candidate
→ validate
→ present
→ UI decide
→ commit
→ checkpoint
```

### 同时实现的核心基础设施

- Task 与 CandidateRevision；
- request ledger；
- `request_id` 幂等；
- `candidate_content_hash`；
- pending nonce；
- DecisionRef；
- `TASK_OPENED`；
- `DECISION_PENDING_OPENED`；
- `DECISION_RECORDED`；
- `COMMITTED`；
- Candidate 防篡改；
- 单产物事务提交；
- `preview_content[]`；
- Pi TUI 中介决定。

### 验收条件

真实 Agent 根据用户想法生成 `premise.md`，作者在 Pi UI 中确认，Core 提交到 `story/premise.md`。模型不能通过工具参数代替作者做决定。

同时必须验证：

- 没有 DecisionRef 不能 commit；
- Candidate 在 present 后被修改时拒绝 commit；
- request 响应丢失后使用相同 `request_id` 重试，不产生第二个 Task 或 Candidate；
- `task open`、`present`、`commit` 后立即运行完整性扫描均通过。

---

## Goal 3：一章纵向切片

增加：

- `story_plan`
- `chapter_plan`
- `chapter_text`
- `claims.yaml`
- `state/current.yaml`
- `state/loops.yaml`
- `export`

运行链：

```text
故事点子
→ premise
→ story plan
→ 第 1 章计划
→ 第 1 章正文
→ claims 投影为 state
→ export
```

### 关键约束

- 状态投影完全由 Core 消费 `claims.yaml` 生成；
- 不增加模型可见的 `state_update`；
- 正文和状态投影使用同一事务；
- export 是派生物，`blocking: false`；
- 一章链路必须同时有 L3 fixture E2E 和真实 Pi 演示。

这一 Goal 完成后，NovelOS 已经具备最小创作价值，而不只是任务管理框架。

---

## Goal 4：替换集合与崩溃恢复

单独实现最复杂的事务场景：

```text
修改第 2 章计划
→ Core 扩展 targets：
   ch-02-plan + ch-02-text
→ Agent 生成两个目标的 Candidate
→ 整集 validate
→ 整集 present
→ 作者一次决定
→ 单事务切换
→ state 重生成
```

替换集合的契约已经在 04、05、06、07 中形成闭环。

### 实现重点

本地文件系统无法天然保证多个文件一次性原子更新。因此应实现的是：

> **NovelOS 可观察状态上的原子性和崩溃可恢复性。**

建议使用：

```text
准备 transaction journal
→ 写入全部临时文件
→ 记录 before/after hash
→ 逐文件 os.replace
→ 更新 accepted 指针与账本
→ 写事务末事件
→ 标记 COMMITTED
```

启动或执行下一命令前：

```text
发现 PREPARED / APPLYING 事务
→ 按 journal 回滚或完成
→ 恢复到完整旧集合或完整新集合
→ 禁止暴露部分提交状态
```

### 必须有的失败注入

- 第二个目标文件写入失败；
- 状态投影写入失败；
- accepted 指针更新失败；
- 事务末事件写入前进程终止；
- 事务完成但响应丢失。

这应当在 L0 中证明，而不是等到 Pilot 才发现。

---

## Goal 5：三章 Strict-Real Pilot

扩展到三章，并执行冻结宪章的固定场景：

```text
完成第 1～2 章
→ 第 3 章计划尚未生成
→ 修改第 2 章计划+正文集合
→ 重新生成状态
→ 完成第 3 章
→ 导出
```

完成：

- G0：L0–L3；
- G1：strict-real 五旗标；
- G2：未参与设计的操作者；
- G3：人工通读；
- evidence package；
- integrity report；
- `task_token_metrics`；
- `run_token_summary`。

Token 通道未完成时必须显示 `UNAVAILABLE`，不能把字数代理量冒充真实 Token 统计。

测试执行节奏按冻结文档执行：

- 每次提交：L0 + L1 + L3；
- Skill、Extension、Task Package 或协议变化：L2 smoke；
- 合并前或定期：L2 全套；
- Pilot 前：L0–L3 全绿。

---

# 三、代码结构建议

不要在第一天建立大量抽象层。建议从以下最小结构开始：

```text
src/novelos/
├─ __main__.py          # 稳定 launcher
├─ cli.py               # 参数 → application 调用 → JSON 信封
├─ protocol.py          # 响应、错误码、协议版本
├─ models.py            # Task/Candidate/Decision 等最小模型
├─ workflow.py          # 合法动作、状态转换
├─ workspace.py         # 目录、读写、布局
├─ events.py            # provenance 与 hash 链
├─ integrity.py         # 两层扫描
├─ transactions.py      # journal、commit、恢复
├─ projections.py       # claims → state
└─ export.py
```

等单文件过大、职责确实分化后再拆包。不要一开始创建几十个 repository/service/manager 类。

Pi 侧：

```text
pi/
├─ extension/
│  ├─ index.ts
│  ├─ core-client.ts
│  ├─ tools.ts
│  └─ ui.ts
└─ skill/
   ├─ SKILL.md
   └─ references/
```

Extension 必须保持薄：

```text
校验模型参数
→ 调 Core
→ 转换 JSON 结果
→ 渲染 UI
```

不得在 TypeScript 中复制工作流状态机。

---

# 四、明确暂不实现的内容

Phase 1/2 中不要顺手加入：

- 完整 Character/World/Arc Domain；
- 多模型客户端；
- SQLite 权威存储；
- 通用历史导航；
- 通用 rollback；
- 分支与合并；
- 多用户并发；
- 自动文学质量评分；
- Web UI；
- 正式插件市场发布；
- 对 1.0 大规模代码迁移。

这些内容即使“很快能做”，也会稀释三章纵向链路。

---

# 五、建议的 Git 工作流

以 `base/develop` 为集成分支，每个 Goal 使用独立短分支：

```text
goal/00-repository-baseline
goal/01-bootstrap-slice
goal/02-premise-loop
goal/03-one-chapter-slice
goal/04-atomic-replacement
goal/05-three-chapter-pilot
```

每个 Goal 一个 Draft PR，PR 必须包含：

- 本 Goal 对应的冻结条款；
- 明确的非目标；
- 实际运行命令；
- 新增测试；
- 已知挂账；
- 至少一个纵向演示证据。

避免一个 Goal 同时覆盖多个里程碑。

---

# 六、现在最应该做的下一步

按顺序执行：

1. 完成冻结文档最后的小补丁；
2. 将十份冻结文档正式提交到 `base/develop`；
3. 更新 README、增加 `AGENTS.md` 和 `TRACEABILITY.md`；
4. 创建 `goal/01-bootstrap-slice`；
5. 只实现 `version/doctor/init/status/next + /novelos`；
6. 在真实 Pi 中从空目录运行一次；
7. 通过后再进入 Premise 闭环。

首个实现 Goal 的完成定义应写成：

```text
在 NovelOS 已安装的前提下，一个空作品目录可以通过 Pi 的 /novelos
完成 Core 版本握手、初始化 Workspace，并显示当前状态与唯一下一步。
全链路使用真实 Extension 和真实 Core launcher，不允许 mock，
不实现 Task、Candidate、Decision 或任何创作领域能力。
```

这一步通过后，说明运行架构成立；下一步才值得实现 Candidate 和作者确认链路。
