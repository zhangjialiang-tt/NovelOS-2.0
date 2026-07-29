**NovelOS 2.0 不应该被定义为 1.0 的重构版，而应该是吸收 1.0 经验后重新设计的第二代产品。**

1.0 的价值，不是留下了多少 Python 代码和 Schema，而是帮你验证了哪些设计思想有效、哪些工程路径成本过高、哪些“通过”其实不代表产品能用。

我建议先冻结一个总判断：

```yaml
NovelOS_2_0:
  product_form: Pi 原生网文创作工作台
  agent_runtime: Pi
  deterministic_core: Python
  model_provider_ownership: Pi
  workflow_authority: NovelOS Core
  user_interface: Pi TUI
  primary_validation: 真实作品纵向闭环
  v1_code_reuse: 按需迁移，不默认继承
```

---

# 一、1.0 留下的核心经验

## 1. 局部正确不等于产品成立

1.0 已经有上千个测试、复杂 Schema、Proposal、Gate、Decision、Baseline 和事务机制，但直到最后跑 E2E Pilot，才发现：

- Prompt 和 Adapter 形状不匹配；
- 阶段 `BLOCKED` 被误判；
- Proposal 没持久化；
- 接口签名不一致；
- Chapter Planner 实际不可用；
- fallback 会掩盖真实路径失败；
- 10/10 PASS 不代表真实创作完成。

  2.0 必须反过来：

> 先建立一条最小真实链路，再扩展横向能力。

## 2. Python 不应该承担 Agent Harness

1.0 的 `model_clients.py`、Prompt 拼装、timeout、重试、CLI 调用、模型输出解析，本质上是在自行实现一套 Agent Runtime。

这些能力不是 NovelOS 的竞争力。

Pi 本身已经提供模型与会话运行时、工具循环、项目级 Skill、Extension、上下文压缩、交互 UI、RPC 和 SDK。项目 Skill 采用渐进加载，完整说明只在任务需要时进入上下文；Extension 可以注册工具、命令、事件和自定义交互界面。([Pi][1])

## 3. 巨型单次输出模式不稳定

1.0 常见模式：

```text
Python 拼接长 Prompt
→ 模型一次返回巨大 JSON
→ Adapter 解析
→ Schema 校验
→ 缺字段或结构不匹配
→ 重试或 fallback
```

这对长篇创作尤其不合适。

2.0 应改成：

```text
NovelOS 创建任务工作包
→ Pi Agent 按需读取文件
→ 生成候选文件
→ 调用 NovelOS validate
→ 根据错误自行修复
→ 作者确认
→ NovelOS commit
```

## 4. 过强的契约增加了成本，却没有同步增加用户价值

1.0 把很多局部对象都提升为正式 Component、Version、Proposal、DecisionPacket。

这些设计证明了事务和审计可以做得很严谨，但对于单用户、本地创作系统，部分机制过重。

2.0 应保留：

- 可追溯；
- 版本失效；
- 作者确认；
- 原子提交；
- 回滚；
- 状态一致性。

但不必保留 1.0 的全部对象层级和 Schema 数量。

## 5. fallback 必须和真实成功严格分开

2.0 的所有运行结果必须标识：

```yaml
source_mode: REAL_AGENT
  DETERMINISTIC_FIXTURE
  FALLBACK
  SEEDED
```

正式验收只能接受：

```text
REAL_AGENT 或 DETERMINISTIC_CORE
```

不能再出现 fallback 后仍显示全链路 PASS。

---

# 二、NovelOS 2.0 的产品定位

建议将 2.0 定义为：

> **运行在 Pi Agent 上、以本地文件为作品事实源、由 Python 确定性内核保障一致性的交互式网文创作工作台。**

它不是：

- 通用 Agent Framework；
- 多模型 SDK；
- 自动化小说生成流水线；
- 复杂内容管理平台；
- 1.0 Schema 的重新包装。

它首先应该解决：

```text
用户进入作品目录
→ 打开 Pi
→ NovelOS 告诉他当前状态和下一步
→ Agent 与用户共同完成创作任务
→ 系统验证并保存
→ 持续推进到下一章
```

---

# 三、2.0 总体架构

```text
┌─────────────────────────────────────────────┐
│ Pi Agent Runtime                            │
│                                             │
│ 会话、模型、上下文、工具循环、用户交互      │
│ Skills、Extensions、Compaction、Session     │
└──────────────────────┬──────────────────────┘
                       │ NovelOS Tools
                       ▼
┌─────────────────────────────────────────────┐
│ NovelOS Python Core                         │
│                                             │
│ 工作流状态、任务、校验、决策、提交、回滚    │
│ 状态连续性、引用解析、导出、运行记录         │
└──────────────────────┬──────────────────────┘
                       │ Files
                       ▼
┌─────────────────────────────────────────────┐
│ Novel Workspace                             │
│                                             │
│ 故事文档、章节、状态、任务、证据、运行日志   │
└─────────────────────────────────────────────┘
```

## 权威边界

### Pi 负责

- 模型选择和调用；
- 多轮对话；
- 追问作者；
- 读取必要上下文；
- 创意设计；
- 候选内容修订；
- 调用 NovelOS 工具；
- 向用户解释结果。

### Python Core 负责

- 当前作品状态；
- 哪些操作合法；
- 输入依赖是否有效；
- Candidate 是否满足结构约束；
- 哪些旧结果已经失效；
- 作者是否已批准当前 revision；
- 文件是否可以提交；
- 状态变化是否连续；
- 提交失败时是否回滚。

### Provider 负责

- 完全属于 Pi 部署配置；
- NovelOS 不关心使用 Qwen、Claude、Codex 或本地模型；
- NovelOS 只声明任务所需能力等级。

Pi 当前支持项目级设置、模型与 thinking level 配置，也支持订阅型和 API Key Provider；这使模型选择可以留在运行环境，不再进入 NovelOS 领域代码。([GitHub][2])

---

# 四、运行形态选择

## 2.0 首选形态：Pi Interactive

用户进入项目：

```bash
cd my-novel
pi
```

然后：

```text
/novelos
```

系统展示：

```text
作品：《停电后的第七层》

当前阶段：第 3 章规划
已完成：
  ✓ 故事方向
  ✓ 一卷大纲
  ✓ 角色与世界规则
  ✓ 6 个 PlotNode
  ✓ 第 1～2 章

当前问题：
  第 3 章尚未完成 ChapterPlan

建议动作：
  创建第 3 章规划
```

这是 2.0 的主要产品形态。

## RPC 和 SDK 的位置

Pi 提供 JSONL RPC、JSON event stream 和 SDK，可用于外部 UI、自动测试或后续桌面应用集成。([Pi][3])

但 2.0 初期不应以 RPC 为主。

建议：

```yaml
runtime_modes:
  interactive:
    priority: PRIMARY
    implementation: Pi TUI + Extension

  test:
    priority: REQUIRED
    implementation: Pi SDK 或 RPC

  headless:
    priority: LATER
    implementation: RPC / JSON mode

  web_ui:
    priority: OUT_OF_SCOPE
```

---

# 五、交互设计

## 1. 单入口，而不是一堆 Skill 命令

用户不应记住：

```text
concept-create
architecture-build
cast-design
world-design
arc-expand
plot-plan
chapter-plan
```

用户只需要：

```text
/novelos
```

或者自然语言：

```text
继续写我的小说
```

NovelOS 查询状态后，给出下一步。

## 2. 标准交互循环

```text
1. status
2. 选择合法动作
3. 创建 Task
4. Agent 完成 Candidate
5. Core validate
6. Agent 修复
7. 向作者展示摘要和关键变化
8. 作者接受 / 修改 / 拒绝
9. Core commit
10. checkpoint
11. next
```

## 3. 作者只在高价值节点确认

2.0 不应每生成一个小对象都要求审批。

建议作者确认点：

- 故事核心方向；
- 完整故事结局；
- 卷级结构；
- 主角核心弧光；
- 关键世界规则；
- StoryArc；
- 章节计划出现重大方向变化时；
- 章节正文定稿；
- 已确认事实的修改。

以下由 Agent 自主处理：

- 字段补全；
- 格式修复；
- 非方向性语言调整；
- 引用补齐；
- Schema 修复；
- 小型节奏优化。

## 4. 三种运行模式

```yaml
interaction_modes:
  guided:
    description: 每个关键决策都与作者确认
    default: true

  assisted:
    description: Agent 连续生成候选，在检查点集中确认

  evaluation:
    description: 固定输入、固定约束、记录全部运行证据
    fallback_allowed: false
```

首版不要做完全自治模式。

---

# 六、2.0 的领域模型应大幅简化

建议放弃“每一种内容都是独立正式领域组件”的思路，改成任务驱动模型。

## 核心对象只保留七个

```text
Project
Artifact
Task
Candidate
Decision
Checkpoint
Run
```

## Task

```yaml
task_id:
task_type:
status:
input_refs:
input_hashes:
current_candidate_revision:
allowed_outputs:
validation_profile:
created_at:
```

## Candidate

```yaml
task_id:
revision:
output_files:
validation_result:
created_by:
source_mode:
```

## Decision

```yaml
task_id:
candidate_revision:
decision: ACCEPT | REVISE | REJECT
author_note:
created_at:
```

## Checkpoint

```yaml
checkpoint_id:
accepted_artifact_refs:
state_snapshot_ref:
content_hash:
created_at:
```

生命周期：

```text
Task OPEN
→ Candidate rev-1
→ VALID / INVALID
→ REVISE
→ Candidate rev-2
→ ACCEPT
→ Checkpoint
```

当 rev-2 创建：

```text
rev-1 自动失效
```

这已经能够覆盖 1.0 中大部分 ProposalFamilyHead 和旧 Packet 拒绝语义，但实现成本低得多。

---

# 七、Workspace 设计

建议文件优先，机器索引第二。

```text
my-novel/
├─ novelos.yaml
├─ story/
│  ├─ premise.md
│  ├─ outline.md
│  ├─ cast.yaml
│  ├─ world.yaml
│  ├─ arcs/
│  ├─ plots/
│  └─ chapters/
├─ state/
│  ├─ current.yaml
│  ├─ characters.yaml
│  ├─ knowledge.yaml
│  ├─ open-loops.yaml
│  └─ timeline.yaml
├─ .novelos/
│  ├─ tasks/
│  ├─ candidates/
│  ├─ decisions.jsonl
│  ├─ events.jsonl
│  ├─ checkpoints/
│  ├─ runs/
│  └─ cache/
└─ .pi/
   ├─ settings.json
   ├─ skills/
   └─ extensions/
```

原则：

- `story/` 和 `state/` 可由人直接阅读；
- `.novelos/` 保存机器运行信息；
- SQLite 可以作为索引或缓存，但不作为唯一事实源；
- Git 用于项目级版本历史；
- NovelOS 自身只保证单次提交的原子性；
- 2.0 首版不解决多人并发编辑。

---

# 八、Task Package：取代巨型 Prompt

每次 Agent 任务生成一个工作包：

```text
.novelos/tasks/task-001/
├─ task.json
├─ instructions.md
├─ context-index.json
├─ context/
│  ├─ current-arc.md
│  ├─ relevant-characters.yaml
│  ├─ relevant-world-rules.yaml
│  ├─ previous-chapter-summary.md
│  └─ current-state.yaml
├─ output-contract.md
└─ output/
```

Pi Agent：

1. 读取 `task.json`；
2. 按需读取 context；
3. 在 `output/` 创建内容；
4. 调用 `novelos_validate`；
5. 根据错误修复；
6. 调用 `novelos_present_candidate`。

正文任务应分成：

```text
draft.md
claims.yaml
```

而不是把几千字正文嵌进 JSON。

---

# 九、Pi 集成设计

## 1. Skill 层

```text
.pi/skills/novelos/
├─ SKILL.md
└─ references/
   ├─ workflow.md
   ├─ story-design.md
   ├─ chapter-planning.md
   ├─ chapter-writing.md
   └─ revision.md
```

Skill 负责教 Agent：

- 何时调用 NovelOS；
- 如何查询状态；
- 如何读取任务；
- 不得直接修改 `.novelos/`；
- 如何处理 validation error；
- 何时询问用户。

Pi 会在启动时只加载 Skill 的名称和描述，完整 Skill 在匹配任务时才按需读取，这正适合减少 NovelOS 大量合同常驻上下文。([Pi][1])

## 2. Extension 层

首版 Extension 提供：

```text
/novelos
/novelos-status
/novelos-resume
```

以及 Agent 工具：

```text
novelos_status
novelos_next
novelos_open_task
novelos_validate
novelos_present
novelos_accept
novelos_revise
novelos_checkpoint
novelos_export
```

Pi Extension 原生支持注册工具、命令、交互确认、自定义 UI 和会话持久状态，因此不需要 NovelOS 自行构建 TUI。([Pi][4])

## 3. Python Core

Extension 不实现领域逻辑，只调用：

```bash
python -m novelos status --json
python -m novelos next --json
python -m novelos validate <task-id> --json
python -m novelos accept <task-id> --revision 2 --json
```

TypeScript 只是薄适配层。

---

# 十、Token 节省策略

2.0 应把 Token 成本列为一等设计指标，而不是运行后才统计。

## 1. 渐进披露

- Skill 只加载当前阶段；
- Context 只包含当前任务依赖；
- Schema 不进入每次 Prompt；
- 完整故事文档通过文件工具按需读取。

## 2. Context Compiler

Python 根据任务生成精确 context：

```yaml
chapter_writer_context:
  include:
    - current_chapter_plan
    - current_plot_node
    - previous_chapter_tail
    - current_character_states
    - referenced_world_rules
    - relevant_open_loops

  exclude:
    - full_architecture
    - unrelated_characters
    - unrelated_world_rules
    - all_previous_chapters
```

## 3. 短期窗口 + 长期状态

不要把全部正文放入会话。

```text
最近 1～2 章原文
+
较早章节摘要
+
结构化当前状态
+
相关伏笔
```

## 4. 阶段 Session

建议：

```text
一个 StoryArc 一个规划 Session
一个 Chapter 一个生产 Session
```

接受章节后创建 checkpoint，并允许新 Session 从结构化状态继续。

Pi 会话可持久化和恢复，也支持上下文压缩；2.0 可以在 checkpoint 后主动压缩或开新 session。([Pi][5])

## 5. 能力等级，而不是绑定模型

NovelOS Task 声明：

```yaml
capability_class: CREATIVE_HIGH
  STRUCTURED_MEDIUM
  REVIEW_MEDIUM
  FORMAT_LOW
```

Pi 运行配置决定具体模型。

## 6. 每次运行记录预算

```yaml
token_metrics:
  input_tokens:
  output_tokens:
  cached_tokens:
  context_files_read:
  retry_count:
  candidate_revisions:
  tokens_per_accepted_1000_chars:
```

重点指标：

```text
每 1000 字定稿正文消耗多少 Token
```

而不是只看总 Token。

---

# 十一、测试体系

2.0 的测试顺序必须反转。

## L0：纯 Python Core

验证：

- Task 状态机；
- Candidate revision；
- 引用和 hash；
- validate；
- accept；
- checkpoint；
- rollback；
- state continuity；
- export。

完全不调用模型。

## L1：CLI / Tool Contract

验证：

```text
Pi Extension 参数
→ Python CLI
→ JSON 输出
```

所有工具必须有稳定机器接口。

## L2：Agent Contract Tests

使用固定 Task Package，检查 Agent 是否：

- 读取正确文件；
- 写入正确目录；
- 调用 validate；
- 遇到错误后修复；
- 不直接改机器元数据；
- 不绕过作者确认。

可以通过 Pi SDK 或 RPC 执行。Pi SDK 支持创建 AgentSession 和自定义工具，RPC 提供 JSON 协议，适合自动化行为测试。([Pi][6])

## L3：Deterministic E2E

使用 fixture candidate：

```text
空项目
→ 初始化
→ 故事规划
→ 章节
→ 状态
→ 导出
```

验证系统工程链。

## L4：Strict Real Pilot

必须满足：

```yaml
strict_real:
  fallback_allowed: false
  seeded_content_allowed: false
  manual_metadata_edit: false
  blocked_stage_causes_failure: true
```

## L5：创作人工验收

人工阅读全文：

- 是否愿意继续读；
- 爽点和悬念是否成立；
- 角色是否连续；
- 伏笔是否兑现；
- 修改是否正确传播。

## 测试原则

每个版本里程碑都必须有一个从空项目开始的纵向场景。

不能再出现：

```text
先积累 1000 个测试
→ 几个月后才跑第一次 E2E
```

---

# 十二、2.0 开发路线

## Phase 0：设计冻结

不写业务代码。

输出：

1. `PRODUCT_DEFINITION.md`
2. `RUNTIME_ARCHITECTURE.md`
3. `PI_INTEGRATION_CONTRACT.md`
4. `INTERACTION_DESIGN.md`
5. `WORKSPACE_AND_ARTIFACT_CONTRACT.md`
6. `TASK_PACKAGE_CONTRACT.md`
7. `TEST_STRATEGY.md`
8. `TOKEN_BUDGET_AND_CONTEXT_STRATEGY.md`
9. `V1_LESSONS_AND_REUSE_MATRIX.md`
10. `V2_PILOT_CHARTER.md`

## Phase 1：最小内核

只实现：

```text
init
status
next
task
validate
accept
checkpoint
export
```

同时实现 Pi Extension 最小入口：

```text
/novelos
```

## Phase 2：三章纵向切片

只支持：

```text
故事点子
→ 简化 Story Plan
→ 3 个 ChapterPlan
→ 3 章正文
→ State Commit
→ Export
```

不实现完整 Character、World、Arc Domain。

成功标准：

```text
真实 Agent
无 fallback
无手工元数据修改
可读完
可中途修改第 2 章计划
```

## Phase 3：八章 Pilot

增加：

- 角色状态；
- 世界规则；
- 伏笔；
- StoryArc；
- 章节 revision；
- rollback；
- 1.5～2 万字。

## Phase 4：长篇能力

只有 Pilot 通过后才考虑：

- 多卷；
- 滚动规划；
- 长期 Promise；
- 大规模角色；
- 多 Agent；
- 自动 Creative Review；
- 正式 Plugin/Package 发布。

---

# 十三、1.0 哪些应该复用

## 概念复用

- Proposal revision 失效思想；
- 作者确认边界；
- Gate 不判断文学质量；
- State 与正文分离；
- 原子提交；
- rollback；
- provenance；
- E2E 证据包；
- strict-real 与 fixture 分离。

## 不默认复用

- 六领域完整划分；
- 全部 ComponentVersion；
- Baseline Registry；
- ProposalFamilyHead；
- DecisionPacket；
- 大量 JSON Schema；
- Python model clients；
- 巨型 Goal 文档；
- 一次性大 JSON 输出；
- 所有 1.0 CLI 和脚本。

## 代码复用原则

```text
2.0 先定义接口
→ 确认需要某项能力
→ 再从 1.0 迁移最小实现
```

而不是先复制代码，再围绕旧代码设计 2.0。

---

# 十四、2.0 的第一性成功标准

2.0 第一阶段成功，不是：

```text
完成 Character Domain
完成 World Domain
完成 Arc Domain
测试达到 1500 项
```

而是：

```text
一个从未接触 NovelOS 的用户
进入一个空目录
打开 Pi
输入一个故事想法
在系统引导下完成三章故事
中途修改一次计划
最终导出正文
全程不需要理解内部 Schema
```

## 最终路线判断

```yaml
recommended_strategy:
  rewrite_type: CLEAN_ARCHITECTURE_RESTART
  reuse_v1: LESSONS_FIRST_CODE_SECOND
  runtime: PI_INTERACTIVE
  integration: THIN_PI_EXTENSION
  core: SMALL_PYTHON_STATE_MACHINE
  storage: HUMAN_READABLE_FILES
  model_clients: REMOVE_FROM_PRODUCTION
  first_milestone: THREE_CHAPTER_VERTICAL_SLICE
  first_large_pilot: EIGHT_CHAPTER_STRICT_REAL
```

**当前第一步不应该创建代码仓库，而应该先完成 Phase 0 的十份冻结文档。**

其中最先写的三份应当是：

```text
1. NovelOS 2.0 Product Definition
2. Agent Runtime and Interaction Architecture
3. Three-Chapter Vertical Slice Pilot Charter
```

只有这三份达成一致，后面的 Workspace、Task Package、测试和 Token 方案才不会再次漂移。

[1]: https://pi.dev/docs/latest/skills?utm_source=chatgpt.com "Skills · Documentation · Pi"
[2]: https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/providers.md?utm_source=chatgpt.com "pi/packages/coding-agent/docs/providers.md at main · earendil-works/pi · GitHub"
[3]: https://pi.dev/docs/latest/rpc?utm_source=chatgpt.com "RPC Mode · Documentation · Pi"
[4]: https://pi.dev/docs/latest/extensions?utm_source=chatgpt.com "Extensions · Documentation · Pi"
[5]: https://pi.dev/docs/latest?utm_source=chatgpt.com "Pi Documentation · Documentation · Pi"
[6]: https://pi.dev/docs/latest/sdk?utm_source=chatgpt.com "SDK · Documentation · Pi"
