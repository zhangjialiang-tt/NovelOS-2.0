# NovelOS 2.0 Task Package Contract

> 冻结文档 07/10 · 上游输入：冻结文档 02 §3.5/§7、冻结文档 04 §2/§3.2–§3.4、冻结文档 06 §1/§4/§5、design.md §八/§十.2/§十.5 · 状态：待确认（r5）
> r2（2026-07-29）：第三轮评审——task.json 增补 brief/target_artifact_ref/replacement 字段、两阶段替换状态持久化、删除 Phase 2 `state_update` 任务类型（状态投影为 Core 确定性生成）。
> r3（2026-07-29）：第四轮评审——replacement 改 targets 集合（整集原子切换）、artifact_change 输出按目标类型分派（正文修改必带 claims.yaml）、接收 artifact 改由 target_artifact_ref 决定、STATE_PROJECTION 禁为直接目标。
> r4（2026-07-29）：第五轮评审——冻结主目标 target_artifact_ref → replacement.targets[] 的确定性扩展规则（依赖闭包）；接收 artifact 由 targets[] 决定。
> r5（2026-07-29）：第六轮评审——"精确目标"残留措辞改主目标、`allowed_outputs` 改 staging 相对路径集、artifact_change context 改多目标、补 Phase 3 闭包规则范围声明。

本文档冻结任务工作包契约：task.json 字段集、包结构、context 编译、output contract、capability_class、包生命周期。工具签名见冻结文档 04 §2；Workspace 布局见冻结文档 06 §1；Token 策略见冻结文档 08。

**冻结**：task.json 字段集、包结构、context 编译 include/exclude、每任务类型 output contract、capability_class 声明、包生命周期。
**不冻结**：instructions.md 文案措辞（要素清单冻结，措辞实现期定稿）、context 文件内部格式细则。

---

## 1. 冻结边界

| 冻结 | 不冻结 |
|---|---|
| task.json 字段名、类型、必填性、语义 | instructions.md 自然语言措辞 |
| 包目录结构与文件职责 | context 摘录排版样式 |
| 每任务类型 context include/exclude 集合 | output 文件的文学内容 |
| 每任务类型 output contract（必产文件、路径、接收 artifact） | 等级→具体模型映射（Pi 部署配置） |
| capability_class 四级声明与默认映射 | Agent 内部执行顺序细节 |
| 包生命周期状态转换 | — |

## 2. task.json schema

存放于 `.novelos/tasks/<task-id>/task.json`，仅 Core 写入（冻结文档 06 §8）。

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `task_id` | string | ✓ | 全局唯一，格式 `task-NNN` |
| `task_type` | enum | ✓ | `premise` \| `story_plan` \| `chapter_plan` \| `chapter_text` \| `artifact_change` |
| `status` | enum | ✓ | `OPEN` \| `AWAITING_DECISION` \| `DONE` \| `REJECTED` \| `BLOCKED` |
| `subject` | string \| null | — | 人类可读任务标题 |
| `brief` | string \| null | — | 短文本输入（premise 初始想法 / 修改说明），编入 context |
| `target_artifact_ref` | string \| null | — | Change Task 的用户请求主目标（`artifact@revision`）；Core 据此计算 `replacement.targets[]`（§2.1） |
| `replacement` | object \| null | — | Change Task 两阶段替换状态（§2.1）；普通任务为 null |
| `inputs` | array | ✓ | `artifact@revision` 引用，绑定 ArtifactRevision（冻结文档 06 §2.3） |
| `input_hashes` | object | ✓ | 各 input 的 hash 快照，STALE_INPUT 检测用（冻结文档 04 §4） |
| `current_candidate_revision` | int \| null | — | 最新 CandidateRevision 序号；无提交时 null |
| `allowed_outputs` | array | ✓ | 允许写入 staging 的 POSIX 相对路径集（相对 `work/<task-id>/`；多目标含 artifact 子目录前缀，如 `ch-02-text/draft.md`、`ch-02-text/claims.yaml`、`change-intent.md`） |
| `validation_profile` | string | ✓ | 校验规则集标识 |
| `capability_class` | enum | ✓ | `CREATIVE_HIGH` \| `STRUCTURED_MEDIUM` \| `REVIEW_MEDIUM` \| `FORMAT_LOW` |
| `created_at` | string | ✓ | ISO-8601 |

状态转换：

```text
OPEN → AWAITING_DECISION（present）→ DONE（ACCEPT）/ OPEN（REVISE）/ REJECTED（REJECT）
OPEN → BLOCKED（依赖失效/上游锁定）→ OPEN（恢复）
```

### 2.1 replacement 字段（仅 Change Task）

```yaml
replacement:
  targets:                        # 替换集合：一个或多个 ArtifactRevision
    - ch-02-plan@1
    - ch-02-text@1
  phase: PREPARING | READY_TO_SWITCH | COMPLETED | CANCELLED
  blocked_downstream_refs: []     # 阶段一锁定的下游 artifact
  change_reason:                  # 来自 open_task 的 brief
```

**targets 派生**：`open_task` 接收用户请求的主目标 `target_artifact_ref`；Core 确定性扩展为替换集合：targets = 主目标 ∪ 传递依赖它的当前 ACCEPTED 产物集合（Phase 2 依赖关系：章节正文依赖章节计划；状态投影不在共替换集合——它在切换事务内确定性重生成）。phase 语义（冻结文档 02 §7.5）：`PREPARING` 下游锁定、旧版保持 ACCEPTED、各目标候选生成并验证；`READY_TO_SWITCH` 集合全部候选验证通过、整集呈现待作者一次决定；`COMPLETED` 整集 ACCEPT、单事务原子切换；`CANCELLED` REJECT/失败，旧基线保持、下游解锁。单产物修改是退化集合（targets 长 1）。持久化于 task.json 使 Core 崩溃可恢复。

范围声明：此确定性闭包规则是 Phase 2 的冻结规则；Phase 3 支持长篇与通用 revision 时，可引入"原子共替换 / 标记 STALE / 延后重生成"的影响分类，不自动继承全量原子替换。

## 3. 包结构

```text
.novelos/tasks/<task-id>/          # 仅 Core 写入；Agent 只读
├─ task.json                       # §2
├─ instructions.md                 # §6 要素
├─ context-index.json              # 来源 artifact/revision/裁剪范围
└─ context/                        # Core 编译的依赖摘录

work/<task-id>/                    # staging：Agent 唯一可写（冻结文档 06 §4）
└─ <output files>                  # §5 output contract
```

`novelos_submit_candidate` 将 staging 复制为内部冻结副本（冻结文档 04 §3.3）。`context-index.json` 供 validate 做 STALE_INPUT 追溯。

## 4. context 编译契约

`novelos_open_task` 时 Core 编译（冻结文档 04 §3.2）；输入依赖失效拒绝编译，返回 `STALE_INPUT`（退出码 1）。

### 4.1 每任务类型 include/exclude

**premise**

| include | exclude |
|---|---|
| 用户初始故事想法（来自 `brief` 字段，Agent 对话收集后经 open_task 传入） | 全部已有产物（首任务无上游） |

**story_plan**

| include | exclude |
|---|---|
| story/premise.md 当前 ArtifactRevision | 完整角色域/世界域（Phase 3+） |
| state/current.yaml（若存在） | 全部章节正文 |

**chapter_plan**

| include | exclude |
|---|---|
| story/plan.md 当前版本 | 无关章节计划与正文 |
| 前一章 plan.md + text.md 尾部 | arcs/plot node（Phase 3+） |
| state/current.yaml + state/loops.yaml 相关子集 | 完整 cast/world 域（Phase 3+） |

**chapter_text**（基线，design.md §十.2）

| include | exclude |
|---|---|
| 当前章 ChapterPlan（ch-NN/plan.md） | 完整架构（plan.md 全文） |
| 前一章尾部（text.md 末段） | 无关角色、无关世界规则 |
| state/current.yaml | 全部过往章节 |
| 被引用世界规则（plan 提取子集） | 完整 cast 域 |
| 相关开放伏笔（loops.yaml 子集） | — |

**artifact_change**

| include | exclude |
|---|---|
| replacement.targets[] 每个目标的当前 ArtifactRevision 全文 | 无关 artifact |
| 受影响下游列表（impact）+ state/current.yaml | 全部过往章节正文 |

### 4.2 Phase 2 简化

arcs/、完整 plot node、完整 cast/world 域属 Phase 3+。Phase 2 以 `plan.md` + `state/` 投影 + `loops.yaml` 为限。

## 5. output contract

Agent 必须写入 `work/<task-id>/` 的文件集；`novelos_validate` 检查齐备性（冻结文档 04 §3.4）。

| task_type | 必产文件 | 接收 artifact |
|---|---|---|
| `premise` | `premise.md` | PREMISE（story/premise.md） |
| `story_plan` | `plan.md` | STORY_PLAN（story/plan.md） |
| `chapter_plan` | `plan.md` | CHAPTER_PLAN（story/chapters/ch-NN/plan.md） |
| `chapter_text` | `draft.md` + `claims.yaml` | CHAPTER_TEXT（story/chapters/ch-NN/text.md） |
| `artifact_change` | 按目标类型分派（§5.1） | 由 `replacement.targets[]` 决定（单产物任务为长度 1 的集合；targets 是 Core 自 `target_artifact_ref` 扩展的依赖闭包，§2.1） |

### 5.1 artifact_change 输出分派

| 目标类型 | 必产文件 |
|---|---|
| PREMISE | `premise.md` + `change-intent.md` |
| STORY_PLAN | `plan.md` + `change-intent.md` |
| CHAPTER_PLAN | `plan.md` + `change-intent.md` |
| CHAPTER_TEXT | `draft.md` + `claims.yaml` + `change-intent.md`（正文修改必带 claims，供投影确定性重生成，文档 06 §5） |

`artifact_change` 不得以 `STATE_PROJECTION` 为直接目标——状态只能经正文 `claims.yaml` 重建，不得重新引入隐形状态任务。替换集合任务（多 targets）staging 按目标 artifact 子目录组织（`work/<task-id>/<artifact-id>/`），文件命名依上表；`change-intent.md` 放任务根目录，描述整个修改。

### 5.2 claims.yaml 字段草图

> **草图**——字段名与结构随实现冻结，本文档仅规定信息类别。

```yaml
chapter: "ch-01"
new_facts: []                  # 本章新引入的世界/剧情事实
character_state_changes: []    # 角色状态变化
resolved_loops: []             # 关闭的伏笔/悬念
new_loops: []                  # 新开的伏笔/悬念
timeline_events: []            # 时间线事件（Phase 3+ 完整 schema）
```

供 Core 投影消费（冻结文档 06 §5）：ACCEPT 后据此确定性地重生成 state/，与正文 commit 同事务。`change-intent.md` 供 present 的 `fact_changes` 与作者审阅。

## 6. instructions.md 模板要素

Core 在 open_task 时生成。要素清单（措辞不冻结）：

| # | 要素 |
|---|---|
| 1 | 任务目的与对应 artifact |
| 2 | 输入清单、context/ 文件用途、按需读取路径 |
| 3 | output contract：必产文件、路径、格式 |
| 4 | validate 常见错误码与修复动作 |
| 5 | 硬规则：work/<task-id>/ 唯一可写；禁触 .novelos/ 与受管文件 |
| 6 | 作者确认告知：present → decide 链路，决定值经 UI |

## 7. capability_class 声明

四级定义见冻结文档 02 §3.5。等级→模型映射是 Pi 部署配置，不是 NovelOS 代码。

| task_type | 默认等级 | 理由 |
|---|---|---|
| `premise` | `CREATIVE_HIGH` | 创意发散 |
| `story_plan` | `STRUCTURED_MEDIUM` | 结构化规划 |
| `chapter_plan` | `STRUCTURED_MEDIUM` | 结构化规划 |
| `chapter_text` | `CREATIVE_HIGH` | 文学创作 |
| `artifact_change` | `REVIEW_MEDIUM` | 审阅 + 定向修改 |

## 8. 包生命周期

```text
open_task → Core 创建 task.json(OPEN) + 编译 context → 返回 package_path/staging_path
Agent 读 instructions + context → 写 work/<task-id>/
submit_candidate → hash + 冻结副本 → CandidateRevision
validate → 通过 → present / 失败 → 改 staging → 新 submit → 再 validate
present → pending decision → status AWAITING_DECISION
decide（UI 中介）：
  ACCEPT → commit → ArtifactRevision → DONE → staging 保留至 checkpoint 后 Core 清理
  REVISE → author_note 注入 → OPEN → 新 Candidate
  REJECT → REJECTED → 包与 staging 保留（审计），status 终态
artifact_change（替换集合）：按目标分别生成与验证候选 → READY_TO_SWITCH → present 整集 → decide：
  ACCEPT → 一个事务原子切换（新版全当前、旧版全 SUPERSEDED、投影重生成）→ DONE
  REJECT / 失败 → CANCELLED，丢弃新候选，旧基线全程保持（文档 02 §7.5）
```

## 9. 待核验项

无。r3 变更均派生自冻结上游（02 §7.5 替换集合、04 §2/§3、06 §2–§6）与 design.md，未引入新 Pi API 声明。

## 10. 文档索引

| # | 文档 | 状态 |
|---|---|---|
| 01–03 | 见冻结文档 01 §13 | 已冻结（02 r5、03 r4、01 r3） |
| 04 | `04-PI_INTEGRATION_CONTRACT.md` | r5，待确认 |
| 05 | `05-INTERACTION_DESIGN.md` | r5，待确认 |
| 06 | `06-WORKSPACE_AND_ARTIFACT_CONTRACT.md` | r5，待确认 |
| 07 | `07-TASK_PACKAGE_CONTRACT.md` | 本文档（r5） |
| 08 | `08-TOKEN_BUDGET_AND_CONTEXT_STRATEGY.md` | 已冻结（r4） |
| 09 | `09-V1_LESSONS_AND_REUSE_MATRIX.md` | 已冻结（r3） |
| 10 | `10-TEST_STRATEGY.md` | r5，待确认 |
