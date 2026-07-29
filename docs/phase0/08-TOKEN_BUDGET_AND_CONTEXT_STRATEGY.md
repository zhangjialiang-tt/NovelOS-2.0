# NovelOS 2.0 Token Budget and Context Strategy

> 冻结文档 08/10 · 上游输入：冻结文档 01 §9.2、冻结文档 02 §3.1/§3.4/§3.5/§11、`docs/design.md` §十 · 状态：已冻结（r4，2026-07-29）
> r2（2026-07-29）：第三轮评审——北极星指标重定义为全运行口径（分子含全部模型任务与返工、分母只计最终当前版本），增设 direct 诊断指标，指标不可用时报 `UNAVAILABLE` 规则。
> r3（2026-07-29）：第四轮评审——token_metrics 拆分为 task_token_metrics / run_token_summary 两级归属，北极星指标归入运行级并增 availability 字段（公式不变）。
> r4（2026-07-29）：第五轮评审——旧 `token_metrics` 措辞统一为 task_token_metrics / run_token_summary（字段与公式不变）。
> 冻结（2026-07-29）：第五轮评审确认 r4 无需再改，本文档完成冻结。

本文档冻结 NovelOS 2.0 的 Token 预算与 context 供给策略：context 供给三层、阶段 Session 策略、`task_token_metrics` / `run_token_summary` 字段集与北极星指标定义、分阶段预算护栏与反膨胀硬规则。本文只冻结策略与字段集，不冻结数值阈值首版取值（给推荐值并标注实现期校准）；Pi 能力断言不超出冻结文档 02 §3 已核验范围。

**冻结**：context 供给三层策略、阶段 Session 策略、`task_token_metrics` / `run_token_summary` 字段集与关键指标定义、预算护栏模式、反膨胀硬规则。
**不冻结**：数值阈值的首版取值（标注校准）、context-index 文件格式（文档 07 §3/§4）、运行记录存放格式（文档 06 §7）、能力等级 → 模型映射（部署配置，文档 02 §3.5）。

---

## 1. 冻结边界

| 冻结 | 权威 / 引用 |
|---|---|
| context 供给三层（Skill references / Core 编译 / 文件按需读取） | 本文 §3；冻结文档 02 §11 |
| 短期窗口 + 长期状态的 context 组装规则 | 本文 §3.4；`design.md` §十.3 |
| 阶段 Session 划分与 checkpoint 后两条续接路径 | 本文 §4；冻结文档 02 §3.4/§11 |
| `task_token_metrics` / `run_token_summary` 字段集与北极星指标计算式 | 本文 §6 |
| 预算护栏的分阶段模式与反膨胀硬规则 | 本文 §7 |

| 不冻结 | 去向 |
|---|---|
| 各阈值首版取值（窗口比例、context 上限、每任务建议预算） | 本文给推荐值，实现期校准 |
| context-index 文件格式与编译产物布局 | 冻结文档 07 §3/§4 |
| `run_record` 存放位置与记录格式 | 冻结文档 06 §7 |
| `capability_class` → 具体模型映射 | 部署配置，冻结文档 02 §3.5 |
| Task 类型枚举、工具签名、JSON 信封 | 冻结文档 07 / 04 |

## 2. 设计原则

1. **Token 成本是一等设计指标，不是运行后统计**（冻结文档 01 §9）。本文的度量与护栏是产品承诺的落地，不是事后报表；context 组装、Session 划分、预算上限都在运行前约束成本。
2. **渐进披露优先于压缩**（`design.md` §十.1；冻结文档 02 §3.1）。先保证"只把当前任务需要的东西放进上下文"，压缩（`compact`）与开新 Session 是披露之后的第二道手段，不用来弥补过度装载。
3. **北极星指标是「每 1000 字定稿正文消耗的 Token」**（冻结文档 01 §9.2）。总 Token 不作为关键指标；成本必须归一化到真实创作产出（accepted 定稿字数），否则"多写多错多重试"会被总量掩盖。

## 3. context 供给三层

三层渐进披露（冻结文档 02 §11），按"常驻 → 按任务 → 按需"递进装载：

| 层 | 供给方 | 内容 | 装载方式 | 引用 |
|---|---|---|---|---|
| Skill 阶段 references | Skill | 当前阶段参考资料（workflow / 规划 / 写作 / 修订） | 启动只载 name + description；阶段匹配时 Agent 用 `read` 载入，不常驻 | 02 §3.1 |
| Core 编译 task context | Python Core | 当前任务依赖的精确 context（context-index） | `open_task` 时按任务类型编译，写入任务工作包 | 07 §4（本文只述策略） |
| 完整故事文档 | Pi 文件工具 | 定稿正文、计划等全量受管文件 | Agent 经 Pi 文件工具按需读取，不进常驻上下文 | 02 §11 |

Core 编译层只述策略：Core 按任务类型生成 include / exclude 集合，纳入当前任务直接依赖、排除全量架构与无关产物；编译产物的文件格式与字段见冻结文档 07 §4，本文不复述。

### 3.4 短期窗口 + 长期状态

不得把全部正文放入会话（`design.md` §十.3）。章节类任务的 context 按下列四段组装：

| 段 | 内容 | 形态 |
|---|---|---|
| 短期窗口 | 最近 1–2 章 | 原文 |
| 长期回溯 | 较早章节 | 摘要 |
| 当前状态 | 角色状态 / 世界规则等结构化投影 | 结构化（`state/`，06 §5） |
| 悬挂线索 | 相关伏笔 / open loops | 结构化子集 |

窗口宽度（最近几章取原文、第几章起转摘要）为首版校准项：推荐最近 1–2 章原文、其余摘要（建议值，实现期校准）。

## 4. 阶段 Session 策略

划分（冻结文档 02 §11，支撑冻结文档 01 产品承诺）：**一个 StoryArc 一个规划 Session，一个 Chapter 一个生产 Session。** checkpoint 后有两条续接路径，均来自 02 §3.4 已核验能力：

| 路径 | Pi 能力（02 §3.4） | 语义 | 适用 |
|---|---|---|---|
| 原地压缩 | `session.compact(customInstructions?)` | 保留同一会话，压缩历史 | 同一任务单元内上下文逼近上限 |
| 开新会话 | `AgentSessionRuntime.newSession()` | 新 Session，从结构化状态恢复 | 自然单元边界（章节 / StoryArc 切换） |

"从结构化状态恢复"指新 Session 不带旧会话历史，而由 §3 三层重新装载：`state/` 结构化投影 + 短期窗口章节尾段 + 相关伏笔。

**两路径选择准则**（阈值均建议值，实现期校准）：

| 条件 | 选择 |
|---|---|
| 章节被 ACCEPT 并 checkpoint，进入下一章 / 新 StoryArc 规划 | 默认 `newSession()`（自然边界，状态已落 `state/`） |
| 同一任务内累计上下文达模型上下文窗口约 2/3（推荐 60–70%，建议值，实现期校准） | `compact()` 原地压缩 |
| REVISE 多轮致历史膨胀但仍在同一任务 | `compact()`，避免丢弃任务内作者备注脉络 |

模型上下文窗口的绝对值由 Pi 部署的模型决定（02 §3.5），NovelOS 只以"占比"表达触发条件，不硬编码 token 数。

## 5. 能力等级与模型非绑定

冻结文档 02 §3.5 已冻结，本文重申其与预算相关的三点，不另立词汇：

- Task 只声明 `capability_class`（枚举 `CREATIVE_HIGH | STRUCTURED_MEDIUM | REVIEW_MEDIUM | FORMAT_LOW`，权威在 02 §3.5）。
- `capability_class` → 具体模型 / thinking level 的映射属 **Pi 部署配置**，不是 NovelOS 领域代码；预算护栏不按模型名分支。
- **NovelOS 不持有任何模型客户端**（1.0 `model_clients.py` 类代码不迁移）；本文一切 token 度量均为对 Pi 运行层用量数据的记录，不含 NovelOS 自发起的模型调用。

## 6. Token 度量 schema（task_token_metrics / run_token_summary）

度量分两级归属——任务级与运行级：

```yaml
task_token_metrics:            # 每任务记录（run_record 按任务聚合）
  input_tokens:                # 任务内全部模型回合输入累计（含失败候选与重试）
  output_tokens:
  cached_tokens:               # 诊断用，不并入总量（见下）
  context_files_read:          # Core 编译进 context-index 的文件数
  retry_count:                 # validate 失败 → 重提交次数
  candidate_revisions:         # 该任务 CandidateRevision 数（02 §7.1）
  direct_writing_tokens_per_1000_chars:  # 诊断指标，仅正文任务（计算式见下）

run_token_summary:             # 运行级
  run_tokens:                  # 全部模型任务 total_tokens 之和
  final_chars:                 # 运行结束时全部当前 ACCEPTED 章节正文字数
  tokens_per_accepted_1000_chars:  # 北极星指标（计算式见下）
  availability: AVAILABLE | UNAVAILABLE
```

来源为 Pi 运行层用量的字段（input/output/cached_tokens）依赖采集通道（文末待核验项）；Core 来源字段不依赖。

总量口径：`total_tokens(t) = input_tokens(t) + output_tokens(t)`，对任务 t 内全部回合累计。`cached_tokens` 单独记录用于诊断缓存命中，**不并入** `total_tokens`——多数 provider 将 cached 计为 input 的子集，重复计入会高估；provider 计费口径属实现期校准。

**北极星指标与计算式**。设 `final_chars(run)` 为运行结束时全部当前 ACCEPTED 的 CHAPTER_TEXT 正文字符总数（按 Unicode code point 计；首版建议含标点、不含纯空白与结构标记——建议值，实现期校准）；设 `run_tokens(run)` 为本次运行**全部模型任务**的 `total_tokens` 之和（含 premise、规划、正文、修改任务，以及 REVISE / REJECT / 失败 Candidate 的全部回合——返工与修改正确计入成本）。

**诊断指标**（直接写作效率，任务口径；`accepted_chars(t)` 为该任务定稿正文字符数）：

```text
direct_writing_tokens_per_1000_chars(t) = total_tokens(t) / accepted_chars(t) × 1000
```

**北极星指标**（全运行口径；分母只计最终当前版本，已 supersede 版本的字符不进分母，因此修改越多指标越真实而非越"好看"）：

```text
tokens_per_accepted_1000_chars(run) = run_tokens(run) / final_chars(run) × 1000
```

指标名与冻结文档 03 §6 一致，本式为权威定义。

存放：每任务 `task_token_metrics` 记入运行记录（冻结文档 06 §7 `run_record`，按任务聚合）；`run_token_summary`（含北极星值与 `availability`）在运行记录中汇总，并经 status / export 报告呈现。**不可用规则**：Phase 2 时若 Pi token 用量通道未就绪（§8），指标报 `UNAVAILABLE`，Pilot 不得声称已完成北极星指标实测；同时记录代理量（字数口径 + `retry_count` + `candidate_revisions`）。

## 7. 预算护栏

护栏分阶段收紧，先度量后约束：

| 阶段 | 模式 | 行为 |
|---|---|---|
| Phase 2（三章 Pilot） | 度量 + 报告 | 记录 `task_token_metrics` / `run_token_summary`，对每任务给建议阈值；超限**记入运行记录但不阻断**任务 |
| Phase 3+（八章及长篇） | 每章预算上限策略 | 在度量基线上引入每章 token 预算上限；超限的呈现与处置随 Phase 3 冻结 |

Phase 2 的"每任务建议阈值"与 Phase 3 的"每章预算上限"具体数值均为首版校准项（建议值，实现期校准），依 Phase 2 实测 `tokens_per_accepted_1000_chars` 基线标定。

**反膨胀硬规则**（任意阶段恒成立）：

| 规则 | 依据 |
|---|---|
| Schema 不进入每次 prompt | `design.md` §十.1 |
| 过往正文不整段嵌入（仅短期窗口原文 + 较早章节摘要） | `design.md` §十.3；本文 §3.4 |
| context-index 编译产物体积设上限 | 推荐单任务 ≤ 32 KB / ≤ ~8k tokens（建议值，实现期校准）；格式见 07 §3/§4 |
| 全量架构 / 无关角色 / 无关世界规则排除出 task context | `design.md` §十.2；07 §4 |

## 8. 待核验项

- **token 用量采集通道**：`input_tokens` / `output_tokens` / `cached_tokens` 需由 Pi 运行层提供每回合用量数据，接口与计费口径未在冻结文档 02 §3 核验，不在本文虚构。**不阻断 Phase 1**（Core 可知字段与链路照常建设）；**必须在 Phase 2 Pilot 前解决，否则北极星指标报 `UNAVAILABLE`**（§6），不得同时声称实测。降级路径：仅记录 `context_files_read` / `retry_count` / `candidate_revisions` 与字数口径，原始 token 字段留空并标记不可用；采集机制确定后回写本文重新冻结。

## 9. 文档索引

| # | 文档 | 状态 |
|---|---|---|
| 01–03 | 见冻结文档 01 §13 | 已冻结（02 r5、03 r4、01 r3） |
| 04 | `04-PI_INTEGRATION_CONTRACT.md` | r5，待确认 |
| 05 | `05-INTERACTION_DESIGN.md` | r5，待确认 |
| 06 | `06-WORKSPACE_AND_ARTIFACT_CONTRACT.md` | r5，待确认 |
| 07 | `07-TASK_PACKAGE_CONTRACT.md` | r5，待确认 |
| 08 | `08-TOKEN_BUDGET_AND_CONTEXT_STRATEGY.md` | 本文档（已冻结 r4） |
| 09 | `09-V1_LESSONS_AND_REUSE_MATRIX.md` | 已冻结（r3） |
| 10 | `10-TEST_STRATEGY.md` | r5，待确认 |
