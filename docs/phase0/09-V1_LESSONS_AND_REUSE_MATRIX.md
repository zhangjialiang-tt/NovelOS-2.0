# NovelOS 2.0 V1 Lessons & Reuse Matrix

> 冻结文档 09/10 · 上游输入：`docs/design.md` §一（1.0 核心经验五条）/§十三（复用判定）、冻结文档 01 §2/§11、冻结文档 02 §3.5/§6.3/§7/§8.1/§12 · 状态：已冻结（r3，2026-07-29）
> r2（2026-07-29）：P0-5 同步——Phase 2 任务类型六→五（`state_update` 移除，状态投影为 Core 在章节 ACCEPT 事务中确定性生成，非模型任务）；同步后即冻结。
> r3（2026-07-29）：第四轮评审同步——rollback 行与 provenance 行对齐"替换集合原子切换"（冻结文档 02 §7.5 r5）与 last_event_id 完整性核验（冻结文档 06 §3.1/§6 r3）。

本文档把 1.0 的经验与复用判定冻结为一张可追溯矩阵：每条产品级教训对应 2.0 对策与冻结落点，每个 1.0 概念/组件对应一个明确的 2.0 判定。**本文档是概念级冻结**——它冻结"复用什么思想、不复用什么对象"，不冻结代码如何搬移。

**冻结**：五条产品级教训→对策→落点映射；代码复用协议与反模式；§十三全部条目的复用判定（复用 / 强化复用 / 概念复用延后 / 不默认复用 / 删除）及其 2.0 落点。
**不冻结**：产品决策的重新论证（见冻结文档 01/02）；v1 代码迁移的具体步骤（v1 代码不在本仓库，按 §3 协议在实现期逐项判定）；Task Package 与测试细节（文档 07/10）。

---

## 1. 冻结边界与范围声明

| 维度 | 本文档冻结 | 本文档不冻结 |
|---|---|---|
| 抽象层级 | 概念级：思想、对象、边界的复用判定 | 代码级：函数、模块、文件的搬移 |
| v1 代码 | 仅以 `docs/design.md` 的复盘叙述为依据 | 任何 v1 代码路径/实现断言——v1 代码不在本仓库，无从核验 |
| 迁移时机 | 判定（复用/不复用/延后）与落点文档 | 迁移顺序、裁剪细节、接口适配——实现期按 §3 逐项判定 |
| 产品决策 | 只引用冻结文档 01/02 的既有结论 | 不重新论证"为什么这样设计" |

范围原则：凡 §4 标注为「复用 / 强化复用」的条目，冻结的是**思想与边界**；其代码是否真从 1.0 搬、搬多少，由实现期按 §3 协议决定。凡标注「不默认复用 / 删除」的条目，2.0 不以 1.0 实现为起点，即使最终写出形似代码也属重新实现，不记为复用。

## 2. 产品级教训表

源：`docs/design.md` §一五条。"冻结落点"列是教训在 2.0 冻结体系中的权威落点，本文档不重复其内容。

| # | 1.0 教训（design.md §一） | 2.0 对策 | 冻结落点 |
|---|---|---|---|
| 1 | 局部正确≠产品成立：上千测试、复杂 Schema、Proposal/Gate/Decision/Baseline 俱全，直到 E2E Pilot 才暴露 Prompt/Adapter 形状不匹配、`BLOCKED` 误判、Proposal 未持久化、Chapter Planner 不可用、fallback 掩盖失败——10/10 PASS 不代表真实创作完成 | 纵向切片优先：先建一条最小真实链路，再扩展横向能力 | 冻结文档 01 §10（MVP 成功标准=真实用户三章纵向闭环）、冻结文档 03（G0–G3 验收门把"真实成立"钉成判据） |
| 2 | Python 不承担 Agent Harness：`model_clients`、Prompt 拼装、timeout/重试、CLI 调用、输出解析本质是自建一套 Agent Runtime，不是 NovelOS 竞争力 | 模型/会话/工具循环/上下文压缩交 Pi，NovelOS 只做 Pi 运行时 + 薄 Extension | 冻结文档 02 §1（总体架构：Pi Runtime 在上、Python Core 在下）、冻结文档 02 §6.3（薄适配原则：每个工具只做三件事） |
| 3 | 巨型单次输出不稳定：拼长 Prompt → 一次返回大 JSON → 解析 → 校验 → 缺字段 → 重试/fallback，对长篇尤其不适合 | 任务工作包 + staging + `validate` 自修复循环：Agent 按需读文件、写候选、调校验、据结构化错误自修复 | 冻结文档 02 §7（Candidate/Decision 链路）、冻结文档 07（Task Package 与 output contract） |
| 4 | 过强契约成本失衡：把局部对象全提升为正式 Component/Version/Proposal/DecisionPacket，事务与审计严谨但对单用户本地系统过重 | 七对象简化为 Task / Candidate / Decision 链路：保留可追溯、版本失效、作者确认、原子提交、状态一致，放弃全部对象层级与 Schema 数量 | 冻结文档 02 §7（三类核心对象链路）、冻结文档 06 §2（Artifact 模型：最小对象集） |
| 5 | fallback 与成功未分离：fallback 后仍显示全链路 PASS | `source_mode` 标识内容来源 + `strict_real` 五旗标；正式验收只接受真实产出 | 冻结文档 01 §9.1（结果来源可辨识）、冻结文档 03 G1（Strict-Real 门：`fallback_allowed: false`） |

教训 5 的一处上游修正：`source_mode` 在 `design.md` §一.5 为四值，验收口径却含 `DETERMINISTIC_CORE`；冻结文档 02 §12 已补第五值并明确 `source_mode` 仅描述内容产生来源（非质量判定）。

## 3. 代码复用协议

```text
2.0 先定义接口
→ 确认需要某项能力
→ 再从 1.0 迁移最小实现
```

**显式反模式（禁止）**：先复制 1.0 代码，再围绕旧代码设计 2.0。这会把 1.0 的对象层级与成本结构原样带进 2.0，直接违反 §2 教训 4。判定先行于代码：§4 矩阵是"要不要、复用什么"的冻结结论；"怎么搬"永远晚于 2.0 自身接口定稿。

每次迁移（仅对判定为「复用 / 强化复用」的条目）必须记录三项，缺一项不得合入：

| 记录项 | 内容 | 约束 |
|---|---|---|
| 来源 | 1.0 中被迁移能力的指认（以 `design.md` 复盘叙述为准） | 不依赖本仓库外的 v1 代码可得性；来源不可核验时按「重新实现」处理，不记为复用 |
| 裁剪理由 | 相对 1.0 删掉了什么、为什么（对齐 §2 某条教训或 §4 某行判定） | 裁剪必须指向已冻结落点，不得就地发明新对象层级 |
| 测试覆盖 | 迁移实现落在哪个测试层（L0–L5，冻结文档 02 §10） | 结构约束进 L0/L1，运行证据进 G1 核验（冻结文档 03） |

判定为「不默认复用 / 删除」的条目不走迁移流程：2.0 需要时重新实现，记录的是新设计的落点，而非 1.0 来源。

## 4. 复用矩阵

覆盖 `docs/design.md` §十三全部条目（概念复用 9 项 + 不默认复用 10 项）。"v1 出处"以 `design.md` 复盘叙述为准，不构成 v1 代码路径断言。

### 4.1 概念复用（9 项）

| 概念/组件 | v1 出处 | 2.0 判定 | 替代或落点 |
|---|---|---|---|
| Proposal revision 失效思想 | 1.0 Proposal revision 失效机制（§十三） | 复用 | CandidateRevision 失效：旧候选失效只是"不再是当前候选"，绝不触及已接受 ArtifactRevision → 冻结文档 02 §7.1；作品版本 SUPERSEDED 只在新版本接受时原子发生 → §7.5 |
| 作者确认边界 | 1.0 作者确认机制（§十三） | 强化复用（UI 中介 + DecisionRef） | 模型参数不含决定值、Extension 经 `ctx.ui` 取值传 Core，Core 状态机绑定 task+revision 一次性消费 → 冻结文档 01 §7、冻结文档 02 §7.3–7.6 |
| Gate 不判断文学质量 | 1.0 Gate 机制（§十三） | 复用 | Core Gate 只判断结构一致性与状态连续性，永不评文学质量；人工可用性判定属作者不属系统 → 冻结文档 01 §11、冻结文档 03 G3 |
| State 与正文分离 | 1.0 State/正文分离（§十三） | 复用 | `state/*.yaml` 是 Core 从已接受产物派生的投影（source_mode `DETERMINISTIC_CORE`），非事实源 → 冻结文档 06 §5 |
| 原子提交 | 1.0 事务机制（§十三） | 复用 | 每次 commit 同事务写 provenance（before/after hash、`writer: NOVEL_OS_CORE`、`decision_ref`）；supersede/STALE 只在 §7.5 阶段二同一事务内发生 → 冻结文档 02 §8.1 |
| rollback | 1.0 回滚机制（§十三） | 概念复用，延后 Phase 3 | 2.0 以替换集合原子切换取代通用 rollback：整集新旧版本一个事务切换，结构上不产生中间态，REJECT/失败时旧基线全程保持、无需 rollback；通用历史版本导航与 rollback 最早 Phase 3 → 冻结文档 01 §11、冻结文档 02 §7.5 |
| provenance | 1.0 provenance 记录（§十三） | 强化复用 | 扩展为全受管文件 hash 账本 + 带外写入检测 + 内部 hash 链；完整性扫描以 `last_event_id` 为权威核验当前 hash 等于合法写事件 `after_hash` → 冻结文档 06 §3.1/§6、冻结文档 03 G1 |
| E2E 证据包 | 1.0 E2E Pilot 证据（§十三） | 强化复用 | 单一证据目录，必含 source_mode 记录、provenance + 完整性扫描、全部 DecisionRef、`events.jsonl`、checkpoints、Token 度量、G0–G3 逐门判定 → 冻结文档 03 §6、冻结文档 06 §7 |
| strict-real 与 fixture 分离 | 1.0 strict_real 思想（§十三） | 强化复用 | strict_real 五旗标 + G1 门以运行证据逐项核验；`manual_metadata_edit` 更名 `out_of_band_managed_write_allowed`，检查扩至全部受管文件；fixture/测试执行归测试层 → 冻结文档 03 G1、冻结文档 10 §3（上游修正见冻结文档 02 §12） |

### 4.2 不默认复用（10 项）

| 概念/组件 | v1 出处 | 2.0 判定 | 替代或落点 |
|---|---|---|---|
| 六领域完整划分 | 1.0 六领域（Character/World/Arc 等）完整划分（§十三） | 不默认复用，Phase 3+ 按需 | Phase 2 只跑纵向切片五任务类型（premise / story_plan / chapter_plan / chapter_text / artifact_change）；状态投影由 Core 确定性生成而非模型任务（冻结文档 06 §5、07 r2）；横向领域按需后置 → 冻结文档 01 §11 |
| 全部 ComponentVersion | 1.0 正式 Component/Version 层级（§十三） | 不复用 | 由 Task / Candidate / Decision 链路与 Artifact 投影替代 → 冻结文档 02 §7、冻结文档 06 §2 |
| Baseline Registry | 1.0 Baseline Registry（§十三） | 不复用 | 同上：当前版本由 ArtifactRevision 状态机表达，无独立基线注册表 → 冻结文档 02 §7、冻结文档 06 §2 |
| ProposalFamilyHead | 1.0 ProposalFamilyHead（§十三） | 不复用 | 同上：候选族简化为单调递增 CandidateRevision → 冻结文档 02 §7、冻结文档 06 §2 |
| DecisionPacket | 1.0 正式 DecisionPacket（§十三） | 不复用 | 统一为单一 Decision 模型 + DecisionRef（ACCEPT/REVISE/REJECT）→ 冻结文档 02 §7.3、冻结文档 06 §2 |
| 大量 JSON Schema | 1.0 复杂 Schema 群（§十三） | 不复用 | 任务工作包携带 output contract，`validate` 返回结构化错误供 Agent 自修复，而非以 Schema 数量设防 → 冻结文档 07（CLI/Schema 数量整体瘦身） |
| Python model clients | 1.0 `model_clients.py` 等（design.md §一.2 点名） | 删除 | 模型/Provider 属 Pi 部署层，移出 NovelOS 生产代码；Core 只声明任务所需能力等级 → 冻结文档 02 §3.5（上游修正见冻结文档 02 §12：`model_clients: REMOVE_FROM_PRODUCTION`） |
| 巨型 Goal 文档 | 1.0 巨型 Goal 文档（§十三） | 不复用 | 由按任务编译的 Task Package（instructions + context 索引）取代 → 冻结文档 07 §6 |
| 一次性大 JSON 输出 | 1.0 "一次返回巨大 JSON"模式（§十三） | 不复用 | 由 output contract 的多文件候选 + `validate` 自修复循环取代 → 冻结文档 07 §5 |
| 全部 1.0 CLI/脚本 | 1.0 全部 CLI 与脚本（§十三） | 不默认复用 | 2.0 重定义工具集（十工具，冻结文档 02 §6.2）+ CLI 动词集与 JSON 信封；1.0 脚本需按 §3 协议逐项判定，不默认继承 → 冻结文档 04 |

## 5. 待核验项

- 本文档未引入冻结文档 02 §3 之外的 Pi API 断言，无 Pi 能力待核验项。
- §4.2 中「Python model clients」是 `design.md` §一.2 直接点名、并在冻结文档 02 §12 以 `REMOVE_FROM_PRODUCTION` 确认的条目；其余 18 项的"v1 出处"均以 `design.md` §一/§十三的复盘叙述为据，因 v1 代码不在本仓库，不构成代码路径级断言，亦无法在此核验其实现细节——这正是 §1 将本文档定为概念级冻结、§3 将代码迁移留给实现期的原因。

## 6. 文档索引

| # | 文档 | 状态 |
|---|---|---|
| 01–03 | 见冻结文档 01 §13 | 已冻结（02 r5、03 r4、01 r3） |
| 04 | `04-PI_INTEGRATION_CONTRACT.md` | r5，待确认 |
| 05 | `05-INTERACTION_DESIGN.md` | r5，待确认 |
| 06 | `06-WORKSPACE_AND_ARTIFACT_CONTRACT.md` | r5，待确认 |
| 07 | `07-TASK_PACKAGE_CONTRACT.md` | r5，待确认 |
| 08 | `08-TOKEN_BUDGET_AND_CONTEXT_STRATEGY.md` | 已冻结（r4） |
| 09 | `09-V1_LESSONS_AND_REUSE_MATRIX.md` | 本文档（已冻结 r3） |
| 10 | `10-TEST_STRATEGY.md` | r5，待确认 |
