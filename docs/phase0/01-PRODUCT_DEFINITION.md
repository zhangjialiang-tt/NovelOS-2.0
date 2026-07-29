# NovelOS 2.0 Product Definition

> 冻结文档 01/10 · 上游输入：`docs/design.md` · 状态：已冻结（r3，2026-07-29）
> r2（2026-07-29）：吸收外部评审——补安装与空目录语义、Candidate 提交与作者授权关节、provenance 语义、统一阶段模型。
> r3（2026-07-29）：第二轮评审——UI-mediated 决定、launcher 抽象、两阶段替换引用、交叉引用修正。

本文档冻结 NovelOS 2.0 的产品层定义：为谁做、是什么、不是什么、以什么形态交付、阶段模型与 MVP 验收。运行架构、Pi 集成契约、Workspace 结构、测试与 Token 细则由后续冻结文档承载，本文只做产品层承诺。

---

## 1. 一句话定位

**运行在 Pi Agent 上、以本地文件为作品事实源、由 Python 确定性内核保障一致性的交互式网文创作工作台。**

## 2. 背景：1.0 的产品级教训

1.0 拥有上千个测试、复杂 Schema、Proposal/Gate/Decision/Baseline 与事务机制，但直到最后一次 E2E Pilot 才暴露：Prompt 与 Adapter 形状不匹配、阶段 `BLOCKED` 被误判、Proposal 未持久化、Chapter Planner 实际不可用、fallback 掩盖真实失败——**10/10 PASS 不代表真实创作完成**。

由此得出四条产品级结论，本文档及后续设计均以其为前提：

1. **先建立一条最小真实链路，再扩展横向能力**；局部正确不等于产品成立。
2. **Python 不承担 Agent Harness**：模型调用、会话、工具循环、上下文压缩交给 Pi，不是 NovelOS 的竞争力所在。
3. **放弃巨型单次输出模式**：不再"拼长 Prompt → 一次返回大 JSON → 解析校验重试"，改为任务工作包 + Agent 按需读写 + 确定性校验 + 作者确认 + 原子提交。
4. **fallback 与真实成功严格分离**：任何运行结果必须标识来源模式，正式验收只接受真实产出。

完整的概念复用 / 代码复用判定矩阵见冻结文档 09 `V1_LESSONS_AND_REUSE_MATRIX.md`。

## 3. 目标用户与核心场景

- **用户**：单作者、本地创作、单机单用户。首版不服务多人协作。
- **核心场景**：

```text
用户进入作品目录
→ 打开 Pi
→ NovelOS 告诉他当前状态和下一步
→ Agent 与用户共同完成创作任务
→ 系统验证并保存
→ 持续推进到下一章
```

- **用户不需要理解**：内部 Schema、任务状态机、引用与 hash 机制、提交与回滚实现。这些是系统责任，不是用户心智负担。

## 4. 是什么 / 不是什么

**是：**

- Pi 原生的创作工作台（Skill + Extension 形态）
- 本地文件驱动的作品管理系统（受管故事文件人类可直接阅读）
- 任务驱动的确定性内核（状态机、校验、原子提交、向前失效）
- 真实创作过程的纵向闭环工具

**不是：**

- 通用 Agent Framework
- 多模型 SDK 或模型路由层（模型选择完全属于 Pi 部署配置）
- 自动化小说生成流水线（首版不做完全自治模式）
- 复杂内容管理平台 / CMS
- 1.0 Schema 的重新包装

## 5. 产品形态与入口

### 5.1 单入口原则

用户不记忆 `concept-create` / `architecture-build` / `chapter-plan` 一类阶段命令。唯一入口：

```bash
cd my-novel
pi
```

```text
/novelos
```

或直接使用自然语言（如"继续写我的小说"）。NovelOS 查询作品状态后给出下一步。

### 5.2 开局状态板

进入作品后系统展示四类信息：

```text
作品：《停电后的第七层》

当前阶段：第 3 章规划
已完成：故事方向 / 一卷大纲 / 角色与世界规则 / 6 个 PlotNode / 第 1～2 章
当前问题：第 3 章尚未完成 ChapterPlan
建议动作：创建第 3 章规划
```

状态板是产品的主界面隐喻：**系统永远先回答"现在在哪、下一步做什么"，再执行任何动作。**

### 5.3 安装前提与"空目录"语义

- **"空目录"指空的作品目录，不代表用户尚未安装 NovelOS。** MVP 场景的前置条件是：NovelOS 已以用户级 Skill/Extension 形式安装，且 Python Core 提供的 launcher 可被 Extension 稳定调用（launcher 形态、解释器发现与版本握手见文档 04）。
- 作品目录不承载 NovelOS 运行代码；`novelos init` 只初始化 Workspace，不负责让 Pi 首次认识 NovelOS。
- Phase 1 提供本地安装方案（安装脚本 / 用户级目录 / 全局 settings 路径项），并自带完整性自检；正式 Plugin/Package 发布仍属 Phase 4。
- 安装形态、诊断分工与启动链路详见冻结文档 02 §4。

## 6. 标准交互循环

每个创作任务遵循同一循环（工具命名见文档 02 §6.2，Candidate 与 Decision 语义见 §7，参数签名见文档 04）：

```text
1.  status — 查询当前状态与合法动作
2.  选择合法动作，创建 Task（Core 编译任务工作包）
3.  Agent 读取工作包与必要作品文件，将 Candidate 写入 staging 区
4.  submit_candidate — Core 接管 staging：hash、冻结副本、分配 candidate revision
5.  validate — Core 对冻结 revision 做纯检查
6.  校验失败：Agent 修改 staging，重新 submit（新 candidate revision）+ validate
7.  校验通过：present — Core 计算确定性变更摘要/差异/影响范围，Extension 向作者渲染
8.  作者 ACCEPT / REVISE / REJECT — 决定值来自 Extension 的 UI 回调，不是 Agent 参数（文档 02 §7.3/§7.6）
9.  ACCEPT → Core 记录 Decision 并原子 commit；REVISE → Task 保持活跃；REJECT → 终止 Task
10. checkpoint
11. next — 回到 1
```

## 7. 作者确认哲学

**只在高价值节点确认，不为每个小对象审批。**

需要作者确认：

- 故事核心方向、完整故事结局、卷级结构
- 主角核心弧光、关键世界规则、StoryArc
- 章节计划出现重大方向变化
- 章节正文定稿
- 已确认事实的修改

Agent 自主处理（不打断作者）：

- 字段补全、格式修复、Schema 修复
- 非方向性语言调整、引用补齐
- 小型节奏优化

**作者决定必须是 Core 可验证的事实，而不是 Extension 的自觉行为或 Agent 的自报值。** 三种决定（ACCEPT / REVISE / REJECT）经两层保障形成 DecisionRef：

1. **UI 中介**：`decide` 是 UI-mediated 工具，模型可提供的参数中不含决定值；决定值由 Extension 经 `ctx.ui` 收集后传给 Core。
2. **Core 状态机**：`present` 开启 pending decision，决定必须绑定 task + candidate revision、一次性消费，ACCEPT 是原子 commit 的唯一合法前提。

其安全语义见文档 02 §7.6：这防御"遵循工具协议的 Agent 跳过交互确认"，不防御绕过工具协议直调内部 CLI，也不防御恶意 Extension。

### 交互模式

```yaml
interaction_modes:
  guided:       # 默认。每个关键决策与作者确认
    default: true
  assisted:     # Agent 连续生成候选，在检查点集中确认（仍是 UI 中介，批量呈现）
  evaluation:   # 固定输入与约束，记录全部运行证据，fallback_allowed: false
```

**首版不做完全自治模式。**

## 8. 运行模式优先级

```yaml
runtime_modes:
  interactive: { priority: PRIMARY,        implementation: Pi TUI + Extension }
  test:        { priority: REQUIRED,       implementation: Pi SDK 或 RPC }
  headless:    { priority: LATER,          implementation: RPC / JSON mode }
  web_ui:      { priority: OUT_OF_SCOPE }
```

交互式是主产品形态；自动化测试是硬需求（否则重演 1.0"几个月后才跑第一次 E2E"）；headless 延后；Web UI 不在 2.0 范围。

## 9. 一等设计指标

以下两项是产品承诺，不是运行后的统计项：

### 9.1 结果来源可辨识

所有内容性产物（Candidate、定稿故事文件）必须标识内容产生来源：

```yaml
source_mode: REAL_AGENT | DETERMINISTIC_FIXTURE | DETERMINISTIC_CORE | FALLBACK | SEEDED
```

**`source_mode` 只描述内容产生来源，不描述确定性处理步骤。** hash、commit、export、状态投影由 Core 执行，记入 `events.jsonl` 的 provenance 事件（writer=NOVEL_OS_CORE），不挤进本枚举——因此定稿章节的 `source_mode` 无歧义地是 `REAL_AGENT`，而落盘它的提交动作是 Core 事件。完整 provenance 链 schema 在文档 06 冻结。

**正式验收只接受 `REAL_AGENT`（真实创作内容）或 `DETERMINISTIC_CORE`（机械派生产物，如导出与状态投影）。** 不允许 fallback 后仍显示全链路 PASS。

### 9.2 Token 成本

关键指标不是总 Token，而是：

```text
每 1000 字定稿正文消耗多少 Token
```

渐进披露、按任务编译 context、阶段 Session 等实现策略见文档 08 `TOKEN_BUDGET_AND_CONTEXT_STRATEGY.md`。

## 10. 阶段模型与 MVP 成功标准

阶段命名全局唯一（与 design.md §十二 一致），三份冻结文档及后续文档统一引用：

| Phase | 名称 | 退出判据 |
|---|---|---|
| 0 | Design Freeze | 十份冻结文档逐份确认 |
| 1 | Runtime Foundation | Core / CLI / Extension / Skill / 安装链路最小闭环；L0–L3 绿；**不宣称产品成立** |
| 2 | 三章 Strict-Real Pilot | 真人 + REAL_AGENT 完成三章纵向切片；G0–G3 通过（见文档 03） |
| 3 | 八章 Pilot | 角色状态 / 世界规则 / 伏笔 / StoryArc；通用 revision 与 rollback；1.5～2 万字 |
| 4 | 长篇能力 | 多卷 / 滚动规划 / 多 Agent / 自动 Creative Review / 正式发布 |

**MVP 成功标准（Phase 2 验收）**——不是"完成 Character / World / Arc Domain"或"测试达到 1500 项"，而是：

```text
一个从未接触 NovelOS 的用户（未参与其设计与实现）
进入一个空作品目录（NovelOS 已安装）
打开 Pi
输入一个故事想法
在系统引导下完成三章故事
中途修改一次已接受的第 2 章
最终导出正文
全程不需要理解内部 Schema
```

该场景的可执行验收门槛（strict-real 约束、完整性证据、角色划分）见文档 03 `V2_PILOT_CHARTER.md`。

## 11. 非目标与延后项

| 延后项 | 最早考虑时点 |
|---|---|
| 多卷 / 滚动规划 / 长期 Promise | Phase 4 |
| 大规模角色管理 | Phase 4 |
| 多 Agent 协作 / 自动 Creative Review | Phase 4 |
| 通用 revision 管理、历史版本导航与 rollback | Phase 3（Phase 2 只含单路径 supersede 与向前失效，且 supersede 只在新版本接受时原子发生——文档 02 §7.5） |
| 多人并发编辑 | 不承诺 |
| Web UI / 桌面应用集成 | OUT_OF_SCOPE（RPC 为其留口，不主动建设） |
| 正式 Plugin/Package 发布 | Phase 4 |
| Core Gate 评判文学质量 | 永不：Gate 只判断结构一致性与状态连续性；Pilot 的人工可用性判定（文档 03 G3）不属于 Core Gate |

## 12. Workspace 写权限原则

产品层冻结一条原则，具体目录在文档 06 冻结：

- Workspace 所有文件均可阅读；**"人类可读"不等于"可以绕过 Core 修改"**。
- Agent 只能直接写入明确标记为 staging 的区域；已接受作品文件与 `.novelos/` 内部状态的写入方只有 Python Core。
- 受管文件由 Core 记录内容 hash；用户在 Core 之外直接编辑受管内容时，Core 在下次操作检测到 hash 失配，标记受影响状态失效并要求经任务受控变更（产品行为在文档 06 冻结；Phase 2 Pilot 将任何此类修改判为失败）。

## 13. 冻结边界与文档索引

**本文档冻结**：产品定位、是什么/不是什么、入口与安装前提、交互循环、确认哲学（UI 中介 + DecisionRef）、运行模式优先级、来源模式与 provenance 语义、阶段模型与 MVP 标准、写权限原则、非目标清单。

**本文档不冻结**：领域对象模型、Workspace 目录结构、工具签名、launcher 与 CLI 语法、Pi 集成实现、测试分层工具、Token 预算数值——均属后续冻结文档。

| # | 文档 | 状态 |
|---|---|---|
| 01 | `01-PRODUCT_DEFINITION.md` | 本文档（r3） |
| 02 | `02-RUNTIME_ARCHITECTURE.md` | r5，已冻结 |
| 03 | `03-V2_PILOT_CHARTER.md` | r4，已冻结 |
| 04 | `04-PI_INTEGRATION_CONTRACT.md` | r5，待确认 |
| 05 | `05-INTERACTION_DESIGN.md` | r5，待确认 |
| 06 | `06-WORKSPACE_AND_ARTIFACT_CONTRACT.md` | r5，待确认 |
| 07 | `07-TASK_PACKAGE_CONTRACT.md` | r5，待确认 |
| 08 | `08-TOKEN_BUDGET_AND_CONTEXT_STRATEGY.md` | 已冻结（r4） |
| 09 | `09-V1_LESSONS_AND_REUSE_MATRIX.md` | 已冻结（r3） |
| 10 | `10-TEST_STRATEGY.md` | r5，待确认 |

> 注：design.md 原列 10 份，其中 `V2_PILOT_CHARTER.md` 为前三优先项之一；本表按"前三份 + 其余"重排编号。04–10 命名与顺序已敲定，状态随各文档确认同步。
