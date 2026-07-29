# NovelOS 2.0 Three-Chapter Vertical Slice Pilot Charter

> 冻结文档 03/10 · 上游输入：`docs/design.md` §十一/§十二、冻结文档 01、冻结文档 02 · 状态：已冻结（r4，2026-07-29）
> r2（2026-07-29）：吸收外部评审——revision 边界重划、修改场景钉死、完整性证据替代 mtime、操作者资格、Bootstrap 与 commit 授权断言。
> r3（2026-07-29）：第二轮评审——修改场景改两阶段替换、诊断分层进 G0、G0/G1 负向/证据分工、字段更名。
> r4（2026-07-29）：第四轮评审——§5 修改场景改为替换集合整集一次决定、一个事务切换（修复分步 ACCEPT 下"旧基线全程有效"不可成立的矛盾，对齐冻结文档 02 §7.5 r5）。

本宪章冻结三章纵向切片试点（冻结文档 01 §10 阶段模型的 Phase 2）的**验收标准与选材准则**。具体题材与故事作品在执行期按本宪章选定，不在此固化。

**冻结**：试点目标与非目标、选材准则、验收门（G0–G3）、strict-real 约束、完整性证据要求、计划修改场景（替换集合原子切换）、失败判定。
**不冻结**：具体作品、Workspace 目录格式（文档 06）、Task Package 细节（文档 07）、测试工具与 fixture（文档 10）。

---

## 1. 试点要证明什么

证明冻结文档 01 §10 的 MVP 成功标准**在真实 Agent 上成立**：

```text
一个从未接触 NovelOS 的用户（未参与其设计与实现）
进入空作品目录（NovelOS 已安装）→ 打开 Pi → 输入故事想法
在系统引导下完成三章故事
中途修改一次已接受的第 2 章
最终导出正文
全程不需要理解内部 Schema
```

**要证明**：最小真实链路端到端可用；任务工作包模式优于巨型单次输出；fallback 与真实成功可辨识地分离；已接受产物的受控替换能正确传播且任何时刻存在有效基线。

**不证明**：长篇能力（多卷、滚动规划）、完整 Character/World/Arc Domain、文学质量优越性、多用户/多 Agent。

## 2. 试点范围

支持的完整链路（与 design.md Phase 2 一致）：

```text
故事点子 → 简化 Story Plan → 3 个 ChapterPlan → 3 章正文 → State Commit → Export
```

**revision 边界（重划）**：通用 revision 管理、历史版本导航与 rollback 属于 Phase 3；Pilot **必须**实现验收场景必需的受控替换——对指定任务产生新候选 revision（CandidateRevision）、经接受形成新作品版本（ArtifactRevision）、单路径 supersede 与向前失效、重新生成；**对已接受产物的修改以替换集合整集原子切换**（一次 ACCEPT、一个事务，冻结文档 02 §7.5），任何时刻旧基线有效。Pilot **不支持**：恢复任意历史 checkpoint、在多个历史 revision 间自由切换、分支合并、通用 rollback、非受控的任意事实修改。

运行配置：`guided` 交互模式（冻结文档 01 §7 默认），interactive 载体（冻结文档 02 §9 PRIMARY）。evaluation 模式不是试点验收路径。

## 3. 选材准则（执行期选作品，不在此指定）

候选故事必须同时满足：

| # | 准则 | 理由 |
|---|---|---|
| S1 | 单主角或双主角，核心角色 ≤5 | 试点不含大规模角色管理 |
| S2 | 单一主线冲突，无多卷结构 | 试点只证单弧光纵向闭环 |
| S3 | 第 2 章存在**天然可修改点**（一个可替换的转折、可更换的对手行动、可调整的信息揭露时机） | 验收强制一次真实的受控替换（§5） |
| S4 | 每章正文目标 2000–3000 字，三章合计 ≥6000 字 | 与 Phase 3 的 8 章 1.5–2 万字密度一致；足以暴露连续性压力，不足以拖垮试点 |
| S5 | 三章内至少包含：一个开场钩子、一次方向性反转、一个跨章悬念的埋设 | 使 G3 人工验收有可判断的对象 |
| S6 | 题材不限，但不得选择需要大量专业知识考据才能判断合理性的题材 | 试点验收者不是领域专家 |

选材产出物：一页《试点作品选定记录》（logline + 每章一句话目标 + S3 修改点描述），存入运行证据包。

## 4. 验收门

四道门**全部通过**才算试点成功。任一门失败即试点失败，修复后从失败门重跑。

### G0 — 工程门（前置，机器判定）

冻结文档 02 §10 定义的 L0–L3 层在试点代码版本上全绿，其中：

**L0 必含负向测试**：

- 无有效 DecisionRef 的 commit 被 Core 拒绝；
- 无 pending 状态的 decide 被拒绝；
- 两阶段替换：新 Candidate 被 REJECT / 失败后，旧 ArtifactRevision 仍为当前版本。

**L1 必含断言**：

- `novelos_decide` 的模型可见参数 schema **不含决定值字段**（UI 中介的结构保障，冻结文档 02 §7.3/§7.6）；
- 诊断分层成立（冻结文档 02 §4.2）：安装器自检能检出不完整安装；`novelos doctor` 能检出 Pi 资产缺失与版本不合。

**L2 至少覆盖**：读对文件、只写 staging、调用 submit/validate、遇错修复、不改内部状态、不绕过确认；以及 Bootstrap：Extension 已安装但 Python Core 缺失时，`/novelos` 返回含安装建议的可操作诊断。

**L3**：fixture candidate 走完全链路（空项目 → 导出）。

> 诊断能力按层归属：Pi 资产未安装时 `/novelos` 不存在，该情形只能由安装器与 `doctor` 检出，不作为 `/novelos` 的验收项（冻结文档 02 §4.2）。

### G1 — Strict-Real 门（硬约束，运行证据）

```yaml
strict_real:
  fallback_allowed: false
  seeded_content_allowed: false
  out_of_band_managed_write_allowed: false
  blocked_stage_causes_failure: true
  all_commits_authorized: true
```

逐项判定（均以试点真实运行的证据核验）：

- **fallback_allowed: false** — 每个 Candidate 与定稿产物的 `source_mode` 必须是 `REAL_AGENT`（机械派生产物如导出允许 `DETERMINISTIC_CORE`；`source_mode` 语义见冻结文档 01 §9.1）。任何 `FALLBACK` 或 `SEEDED` 出现即失败。
- **seeded_content_allowed: false** — 故事内容（premise、plan、正文）不得预置；只允许空白项目模板与系统脚手架。
- **out_of_band_managed_write_allowed: false** — 以**完整性证据链**核验，不以 mtime 为主判定：每次 Core commit 写 provenance 记录（artifact_path、before/after 内容 hash、writer=NOVEL_OS_CORE、event_id、task_id、candidate_revision、decision_ref；冻结文档 02 §8.1）；试点结束执行完整性扫描：全部受管文件当前 hash 必须等于最后一次合法 commit 的 `after_hash`，任何失配标记 `TAMPERED` 并使此门失败。mtime 只作辅助证据。Agent 或人工对受管/内部文件的带外写入同样经此扫描检出。
- **blocked_stage_causes_failure: true** — 任何阶段 `BLOCKED` 必须使运行显式失败并停止，不得被跳过或降级继续。
- **all_commits_authorized: true** — 运行中每一次成功 commit 的 provenance 记录都携带有效且一次性消费的 DecisionRef，来源为 `INTERACTIVE_UI`（对应的 Core 拒绝负向测试在 G0）。

### G2 — 场景门（真人操作）

**角色划分**：

- **Pilot operator**：执行全流程，验证产品是否能被新用户使用。**必须未参与 NovelOS 设计或实现**，且此前未完整使用过 NovelOS；产品作者 / 开发者不得担任。
- **Story author**：做内容方向确认与 G3 判断。
- **Observer**：记录 schema 泄漏、人工介入与失败。

同一人可兼任 operator 与 story author，但不得是 NovelOS 设计者或实现者。

流程：

1. 空作品目录 `cd my-novel && pi`，`/novelos` 或自然语言进入；
2. 口述故事想法，在系统引导下完成三章；
3. 按 §5 固定场景注入第 2 章修改，系统正确传播；
4. 导出正文（单一可读产物）；
5. 全程 operator **不需要理解内部 Schema**——判定方式：operator 未打开 `.novelos/` 内任何文件、未询问字段含义即可完成。需要人工解释 schema 才能继续记一次"schema 泄漏"，≥1 次即此门失败。

### G3 — 人工可用性验收（最小线）

**G3 是产品人工可用性判定，不属于 Core Gate，也不形成可自动执行的文学评分标准**（与冻结文档 01 §11"Core Gate 不判断文学质量"无冲突：此处的判断者是作者，不是系统）。

作者通读三章定稿，以下三项全部为"是"：

- 愿意继续读第 4 章（若存在）；
- 第 2 章修改后的版本与第 1、3 章无明显矛盾（角色行为、已确立事实、悬念状态）；
- 至少一个跨章悬念被正确埋设且未被修改破坏。

## 5. 强制计划修改场景（钉死为唯一场景，替换集合原子切换）

前置状态固定：

```text
第 1 章正文已接受
第 2 章计划与正文已接受
第 3 章计划尚未生成
```

**阶段一：准备替换**（验收对象：旧基线不受损）

```text
作者按选材记录 S3 对第 2 章关键转折提出方向修改
→ 创建 Replacement Task，replacement.targets = [ch-02-plan@当前, ch-02-text@当前]
→ Core 计算 impact，第 3 章规划被锁定（legal_actions 排除基于第 2 章旧版本的新工作）
→ 第 2 章旧计划与旧正文保持 ACCEPTED（仍是当前版本），状态投影保持有效
→ Agent 按目标分别生成新计划候选（plan.md）与新正文候选（draft.md + claims.yaml），各自 submit + validate
→ 两者全部通过 → replacement.phase = READY_TO_SWITCH
```

**阶段二：整集一次决定、一个事务切换**（验收对象：传播完整性 + 事务安全）

```text
present 展示整个替换集合：新计划 + 新正文 + fact_changes + impact（确认前全文来自 preview_content）
→ 作者对集合做一次 ACCEPT / REVISE / REJECT
→ ACCEPT（一个事务内）：
   新计划成为当前版本、新正文成为当前版本
   旧计划与旧正文同时标记 SUPERSEDED
   状态投影据新 claims.yaml 重生成
   第 3 章规划解除锁定，只能基于新接受的 ArtifactRevision 生成
   replacement.phase = COMPLETED
→ 全部 supersede / 决定记入 events.jsonl / decisions.jsonl（同一 transaction_id）
```

**取消安全性（验收对象）**：切换是整集原子事务，不存在"部分接受"中间态；任一候选 REJECT 或生成失败时，取消 Replacement Task（phase = CANCELLED）后旧第 2 章计划与正文仍为当前版本，第 3 章锁定解除——无需 rollback，作品始终有有效基线（冻结文档 02 §7.5）。

此场景覆盖 design.md Phase 2"可中途修改第 2 章计划"并强化到**已接受正文的受控替换**——修改传播的最小完整集。验收点不是"能改"，而是传播完整性与事务安全：没有孤儿引用、没有基于旧版本的第 3 章、没有静默覆盖、结构上不产生"旧版已废新版未立"的中间态。

## 6. 证据包要求

试点运行必须产出单一证据目录（结构细则见文档 10，此处冻结必含项）：

- 每任务的 `source_mode` 记录（全部 Candidate 与定稿产物；语义：内容产生来源）；
- 全部 commit 的 provenance 记录（含 decision_ref 与来源）+ 试点结束时的**完整性扫描报告**（§4 G1）；
- 全部 DecisionRef（task、CandidateRevision、决定类型、来源 INTERACTIVE_UI、一次性消费标记）；
- `decisions.jsonl` 与 `events.jsonl`（含 §5 替换集合的锁定 / supersede / 解锁事件，同一 transaction_id）；
- checkpoints 序列与最终导出产物；
- Token 度量：每任务的 input/output/cached tokens、retry_count、candidate_revisions，汇总指标 `tokens_per_accepted_1000_chars`（冻结文档 01 §9.2）；
- 《试点作品选定记录》（§3）；
- G0–G3 逐门判定结果与判定依据。

## 7. 失败判定速查

出现以下任一现象，试点直接判负（不论其他门状态）：

1. fallback/seeded 产物出现在定稿链路而 `source_mode` 未如实标记；
2. 完整性扫描出现 `TAMPERED`（含 `.novelos/` 或受管作品文件被人工/Agent 带外修改）；
3. 存在无有效 DecisionRef（或来源非 INTERACTIVE_UI）的成功 commit；
4. `BLOCKED` 阶段被跳过或降级继续；
5. 计划修改后存在基于旧 ArtifactRevision 的下游产物，或替换过程中出现"旧版已废、新版未接受"的中间态被持久化；
6. 状态不连续（commit 间状态快照无法衔接）；
7. 无法导出，或导出产物与定稿不一致。

## 8. 与测试分层的关系

层边界定义在冻结文档 02 §10；对应关系：

```text
L0/L1/L3 ── G0（持续运行，试点前置；含负向测试与诊断分层断言）
L2       ── G0（Agent 行为契约 + Bootstrap 项）
L4       ── G1 + G2（strict-real 纵向场景，本宪章主体）
L5       ── G3（人工可用性判定）
```

试点通过后，Phase 3（八章 Pilot）在本宪章基础上扩展通用 revision/rollback，不另起验收哲学。

## 9. 文档索引

| # | 文档 | 状态 |
|---|---|---|
| 01 | `01-PRODUCT_DEFINITION.md` | r3，已冻结 |
| 02 | `02-RUNTIME_ARCHITECTURE.md` | r5，已冻结 |
| 03 | `03-V2_PILOT_CHARTER.md` | 本文档（r4） |
| 04–10 | 见冻结文档 01 §13 | r5 轮：04–07/10 待确认，08/09 已冻结 |
