# NovelOS 2.0 Runtime Architecture

> 冻结文档 02/10 · 上游输入：`docs/design.md`、冻结文档 01 · Pi 官方文档核验基准：pi.dev/docs/latest，2026-07-29 · 状态：已冻结（r5，2026-07-29）
> r2（2026-07-29）：吸收外部评审——两级安装模型、Candidate staging 与 submit、DecisionRef 授权、写权限矩阵、L0–L5 层边界、统一 decision 词汇。
> r3（2026-07-29）：第二轮评审——UI-mediated decide、诊断职责三层拆分、两阶段替换事务、CandidateRevision/ArtifactRevision 概念分离、launcher 抽象、交叉引用修正。
> r4（2026-07-29）：微补——§6.2 工具表新增 `novelos_init`（否则 §4.3 启动闭环无正式工具入口）；工具数 9→10，签名见冻结文档 04 §2。
> r5（2026-07-29）：第四轮评审——§7.5 替换改为集合原子切换（修复分步 ACCEPT 与"旧基线全程有效"的深层矛盾）；§7.4 pending/DecisionRef 绑定 candidate_content_hash；decide 示例补 --nonce。

本文档冻结 NovelOS 2.0 的运行时架构：三层结构、权威边界、安装与启动模型、对 Pi 能力的依赖基线（全部经官方文档核验）、三层集成分工、Candidate 与 Decision 链路、运行模式映射、测试层边界。所有 Pi 接口断言附来源；2026-07-29 之后 Pi 版本变动以集成时复核为准。

**冻结**：架构分层、权威边界与写权限、安装/启动与诊断分工、Pi 能力依赖清单、Skill/Extension/Core 分工、两类 revision 概念、Candidate 与 Decision 链路（含 UI 中介与两阶段替换）、运行模式映射、L0–L5 层边界。
**不冻结**：工具参数表与 JSON 字段（文档 04）、launcher 形态与版本握手（文档 04）、Skill 正文（实现期）、Workspace 目录格式（文档 06）、Task Package（文档 07）、测试实现与 fixture（文档 10）、Token 预算（文档 08）。

---

## 1. 总体架构

```text
┌─────────────────────────────────────────────┐
│ Pi Agent Runtime                            │
│ 会话、模型、上下文、工具循环、用户交互      │
│ Skills、Extensions、Compaction、Session     │
└──────────────────────┬──────────────────────┘
                       │ NovelOS Extension（Pi 进程内唯一集成组件）
                       ▼
┌─────────────────────────────────────────────┐
│ NovelOS Python Core（独立子进程）           │
│ 工作流状态、任务、校验、决策、提交          │
│ 状态连续性、引用解析、导出、运行记录        │
└──────────────────────┬──────────────────────┘
                       │ Files
                       ▼
┌─────────────────────────────────────────────┐
│ Novel Workspace                             │
│ 受管故事文件、staging、内部状态、导出       │
└─────────────────────────────────────────────┘
```

NovelOS 不实现 Agent Runtime。模型调用、多轮对话、上下文压缩、工具循环、TUI 全部由 Pi 承担。**Extension 是 NovelOS 在 Pi 进程内的唯一集成组件；Python Core 作为独立子进程执行全部确定性领域逻辑。**

## 2. 权威边界

### 2.1 判定权威

| 判定 | 权威方 |
|---|---|
| 模型选择、thinking level、provider 配置 | Pi 部署配置 |
| 多轮对话、追问作者、创意设计、候选修订 | Pi Agent |
| 调用哪些 NovelOS 工具、何时调用 | Pi Agent（由 Skill 教导） |
| 作者决定的取值 | Extension 经 UI 收集（§7.3），Core 验证其有效性 |
| 当前作品状态、哪些操作合法 | Python Core |
| 输入依赖是否有效、Candidate 是否满足结构约束 | Python Core |
| 哪些旧结果失效、DecisionRef 是否可消费 | Python Core |
| 文件是否可以提交、状态变化是否连续 | Python Core |
| 文学质量 | 不属于系统判定，归作者（冻结文档 01 §11） |

**仲裁规则**：任何"合法性 / 一致性"争议以 Python Core 的确定性判定为准；Pi Agent 不得通过直接修改内部状态或受管作品文件绕过 Core。此规则同时写入 Skill 正文（§5）。

### 2.2 写权限矩阵

| 区域 | 可读 | Agent 直接写 | 提交 / 落盘 |
|---|---|---|---|
| 受管故事文件（定稿正文、计划、状态投影；目录名文档 06 冻结） | 所有人 | ✗ | 仅 Python Core |
| staging 候选区 | 所有人 | ✓（Agent 唯一可写路径） | Core 经 submit 接管 |
| `.novelos/` 内部状态 | 用户可读 | ✗ | 仅 Python Core |
| 导出物 | 所有人 | ✗ | Python Core（可重新生成） |

受管文件由 Core 记录内容 hash；用户在 Core 之外直接编辑受管内容时，Core 在下次操作检测到 hash 失配，标记受影响状态 STALE 并要求经任务受控变更（产品级 reconcile 流程在文档 06 冻结；Phase 2 Pilot 将任何此类修改判为失败，见文档 03 G1）。

## 3. Pi 能力基线（已核验）

### 3.1 Skills

核验事实（[skills][1]）：

- Skill 是按需加载的能力包，实现 [Agent Skills 标准](https://agentskills.io/specification)。
- **渐进披露**：启动时 Pi 只扫描并提取 name 与 description 写入系统提示（XML 格式）；任务匹配时 Agent 用 `read` 加载完整 `SKILL.md`。
- 位置：**用户级 `~/.pi/agent/skills/`（全局，所有项目）**；项目级 `.pi/skills/`（项目被信任后加载）；全局 `settings.json` 的 `skills` 数组可加路径。含 `SKILL.md` 的目录递归发现。
- Frontmatter 硬约束：`name` 必填，≤64 字符，仅小写字母/数字/连字符；`description` 必填，≤1024 字符；**缺 description 的 skill 不加载**。Pi 不要求 name 与目录同名。
- Skill 命令形如 `/skill:name`，需 `settings.json` 中 `enableSkillCommands: true` 才可用。

NovelOS 用法：Skill 只负责"教 Agent 如何用 NovelOS"（何时查状态、如何读任务、写 staging 而非内部状态、validation error 如何处理、何时问用户）。分阶段参考资料放 `references/`，按需加载，不常驻上下文。

### 3.2 Extensions

核验事实（[extensions][2]）：

- TypeScript 模块，默认导出 `(pi: ExtensionAPI) => void` 工厂；经 jiti 加载，无需编译。
- 位置：**用户级 `~/.pi/agent/extensions/*.ts` 或 `*/index.ts`（全局）**；项目级 `.pi/extensions/`（信任后加载）；全局 `settings.json` 的 `extensions` 数组可加路径；自动发现位置支持 `/reload` 热重载。
- 可注册：`pi.registerTool()`（LLM 可调用工具，参数用 typebox `Type.Object` 定义，`execute(toolCallId, params, signal, onUpdate, ctx)` 返回 `{ content, details }`）、`pi.registerCommand()`（`/mycommand` 式命令）、`pi.registerShortcut()`、`pi.registerFlag()`、`pi.registerProvider()`。
- 事件订阅 `pi.on(...)`：可拦截/阻断工具调用（`tool_call` 返回 `{ block: true, reason }`）、注入上下文、定制 compaction。
- 用户交互 `ctx.ui`：`select / confirm / input / editor / notify / setStatus / setWidget / custom()`。
- **UI 可用性**：`ctx.hasUI` 在 TUI 与 RPC 模式为 `true`，在 print（`-p`）与 JSON 模式为 `false`；TUI 专属能力（`custom()`、组件工厂、终端输入）须以 `ctx.mode === "tui"` 守卫。
- 会话持久化：`pi.appendEntry()` 写入跨重启存活的状态。
- 可用依赖：`@earendil-works/pi-coding-agent`（类型）、`typebox`、`@earendil-works/pi-ai`、`@earendil-works/pi-tui`；npm 依赖需在扩展旁放 `package.json`。
- 官方告诫：工厂函数可能运行在不启动会话的调用中——**不要在工厂里启动后台资源**，推迟到 `session_start`，并注册幂等的 `session_shutdown` 处理。

NovelOS 用法：Extension 注册 `/novelos` 等命令与 §6.2 工具集；作者确认经 `ctx.ui`（以 `hasUI` + `ctx.mode` 守卫，确认策略见 §9）；Extension 本体是薄适配层，不实现领域逻辑（§6.3）。

### 3.3 RPC

核验事实（[rpc][3]）：

- `pi --mode rpc`：stdin/stdout 上的 JSON 协议，用于嵌入其他应用/自定义 UI。
- **严格 JSONL，仅 LF（`\n`）分帧**；Node `readline` 因额外切分 `U+2028/U+2029` 而不协议兼容，客户端必须自行按 `\n` 切分。
- 命令：`prompt`（支持 images、`streamingBehavior: steer|followUp`）、`steer`、`follow_up`、`abort`、`new_session`、`get_state`、`get_messages`、`set_model`、`cycle_model`、`set_session_name` 等；可选 `id` 做请求/响应关联；事件以 JSON line 流式输出。
- 官方建议：Node.js/TypeScript 应用优先考虑直接用 SDK 的 `AgentSession`，而非 spawn 子进程。

NovelOS 用法：RPC 仅用于 headless（LATER 优先级）。任何消费 RPC 输出的 NovelOS 组件必须自实现 LF 分帧。

### 3.4 SDK

核验事实（[sdk][4]）：

- SDK 包含在主包：`npm install @earendil-works/pi-coding-agent`（**不是** draft.md 所写的 `@mariozechner/pi-coding-agent`，该包名已过时）。
- `createAgentSession({ sessionManager, modelRuntime, model, tools, ... })` → `{ session }`；`SessionManager.inMemory()` 支持无盘会话。
- `AgentSession` 接口：`prompt(text, options)`、`steer()`、`followUp()`、`subscribe(listener) → unsubscribe`、`messages`、`isStreaming`、`setModel()`、`setThinkingLevel()`、`compact(customInstructions?)`、`navigateTree()`、`abort()`、`dispose()`。
- `createAgentSessionRuntime()` 负责会话替换（`newSession / switchSession / fork / importFromJsonl`），与内置 interactive/print/RPC 模式同层。

NovelOS 用法：SDK 是 L2 Agent Contract Tests 的首选执行器；也是后续桌面集成的入口。interactive 产品形态不依赖 SDK。

### 3.5 Provider 与模型

核验事实：模型与 thinking level 由 Pi 管理——交互式可切换，RPC 有 `set_model/cycle_model`，CLI 有 `--provider/--model <provider/id:thinking>`（[rpc][3]）；provider 配置属于 Pi 部署层（[providers][5]）。

NovelOS 用法：NovelOS 不持有任何模型客户端（1.0 的 `model_clients.py` 类代码不迁移）。Task 只声明能力等级：

```yaml
capability_class: CREATIVE_HIGH | STRUCTURED_MEDIUM | REVIEW_MEDIUM | FORMAT_LOW
```

具体模型由 Pi 运行配置决定。能力等级 → 模型的映射规则是部署配置，不是 NovelOS 领域代码。

## 4. 安装、诊断与启动

### 4.1 两级安装

```text
用户级安装（主落点，Phase 1 = 本地安装脚本）
├─ ~/.pi/agent/skills/novelos/        # 或全局 settings.json 的 skills 路径项
├─ ~/.pi/agent/extensions/novelos/    # 或全局 settings.json 的 extensions 路径项
└─ Python Core 包（提供 launcher；调用形态见 §4.2 与文档 04）

作品目录（每个故事）
└─ 仅 Workspace：受管故事文件 / staging / .novelos/ / 导出物（§2.2）
```

- **项目级 `.pi/skills|extensions` 仅作为 NovelOS 自身开发仓的有效落点**；产品用户不依赖它——项目级加载受信任门控，无法在空目录首次启动时存在。
- "空目录" = 空的作品目录（冻结文档 01 §5.3）。安装有两半：Pi 资产（Skill + Extension）与 Python Core，缺一不可。
- 正式 Plugin/Package 分发（`pi install`、npm/git 包）仍属 Phase 4；Phase 1 的本地安装脚本必须同时完成两半并自检。

### 4.2 Core launcher 与诊断分工

Python Core 向 Extension 暴露一个可稳定调用的 launcher（本文档以下示例以 `python -m novelos` 作**示意语法，非冻结接口**）；launcher 的具体形态（模块调用 / console script）、解释器发现、版本握手在文档 04 冻结。

诊断职责分三层——**系统不能诊断"负责诊断自己的组件不存在"，因此每一层只负责自己能观测的故障**：

| 层 | 执行者 | 负责诊断 |
|---|---|---|
| 安装自检 | 安装脚本（Phase 1） | Pi 资产与 Python Core 两半是否都安装到位；失败给出缺失项与安装命令 |
| `novelos doctor` | Python Core（终端直接运行，不经 Pi） | Core 已存在前提下：Skill/Extension 落点是否就位、版本兼容性、settings 路径项 |
| `/novelos` 运行时诊断 | Extension（已加载后） | Python Core 缺失或不兼容、Workspace 未初始化、开发仓项目级资产未信任、Workspace 损坏或 hash 失配 |

"Pi 资产未安装"只能由前两层检出；Extension 不存在时 `/novelos` 根本不会注册，不承担此诊断。上述分层在 L1/L2 测试中断言（文档 03 G0）。

### 4.3 启动闭环

```text
/novelos
→ Extension 调用 Core status
→ 未初始化：Core 返回 { initialized: false, legal_actions: [init] }
→ init 初始化 Workspace（创建受管区 / staging / .novelos/）
→ status 返回状态板 + legal_actions
→ 其后进入标准交互循环（冻结文档 01 §6）
```

## 5. Skill 层设计

```text
~/.pi/agent/skills/novelos/      # 用户级主落点
├─ SKILL.md
└─ references/
   ├─ workflow.md
   ├─ story-design.md
   ├─ chapter-planning.md
   ├─ chapter-writing.md
   └─ revision.md
```

- `name: novelos`；`description` 必须精确描述触发时机（≤1024 字符），因为它是唯一的加载信号。
- SKILL.md 正文保持薄：入口用法 + 硬性规则（只能写 staging；不得修改 `.novelos/` 与受管作品文件；validate 失败必须修复而非绕过；决定必须经 present → decide 链路且决定值来自 UI），阶段细节下沉到 `references/`，利用渐进披露按需进入上下文。
- `/novelos` 入口**不是** skill 命令：skill 命令形如 `/skill:name` 且默认关闭。`/novelos` 由 Extension `registerCommand` 注册（原生支持 `/mycommand` 式命令，无需额外开关）。

## 6. Extension 层设计

### 6.1 落点与形态

```text
~/.pi/agent/extensions/novelos/  # 用户级主落点
├─ index.ts          # 默认导出工厂：只注册，不启动后台资源
├─ tools.ts          # 工具注册（薄适配：spawn Core launcher，解析 JSON）
├─ commands.ts       # /novelos、/novelos-status、/novelos-resume
└─ package.json      # npm 依赖（如需要）
```

任何后台资源推迟到 `session_start`，`session_shutdown` 幂等清理（官方告诫）。作者确认走 `ctx.ui.confirm/select`（守卫与策略见 §9）；无 UI 模式下需要确认的任务由 Core 拒绝进入，而非由 Extension 变通。

### 6.2 命令与工具

命令（冻结文档 01 §5.1 单入口原则的落地）：

```text
/novelos            # 状态板 + 下一步建议
/novelos-status     # 纯状态查询
/novelos-resume     # 从中断处继续
```

工具按调用性质分两类（签名字段在文档 04 冻结）：

| 工具 | 性质 | 说明 |
|---|---|---|
| `novelos_init` | Agent 可调用 | 初始化 Workspace（未初始化时唯一入口，§4.3） |
| `novelos_status` | Agent 可调用 | 状态与合法动作 |
| `novelos_next` | Agent 可调用 | 下一步建议 |
| `novelos_open_task` | Agent 可调用 | 创建/打开 Task，Core 编译任务工作包 |
| `novelos_submit_candidate` | Agent 可调用 | 接管 staging：hash、冻结副本、分配 candidate revision |
| `novelos_validate` | Agent 可调用 | 对指定 revision 的纯确定性检查 |
| `novelos_present` | Agent 可调用 | Core 计算确定性变更摘要/差异/影响范围并开启 pending decision |
| `novelos_decide` | **UI 中介** | 模型参数**不含决定值**；Extension 经 `ctx.ui` 收集 ACCEPT/REVISE/REJECT 与作者备注后传 Core（§7.3） |
| `novelos_checkpoint` | Agent 可调用 | checkpoint |
| `novelos_export` | Agent 可调用 | 导出 |

### 6.3 薄适配原则

Extension 的每个工具实现只做三件事：

```text
1. 校验/转换参数（decide：经 ctx.ui 取得决定值）
2. 调用 Core launcher（child_process spawn）
3. 解析 JSON 输出，映射为 Pi tool result
```

领域逻辑零实现。判定标准：若某段逻辑在 Python Core 单测（L0）中无法覆盖，它就不该出现在 Extension 里。变更摘要、差异与影响范围由 Core 确定性计算，Extension 只渲染；面向作者的语义讲述由 Agent 在对话中自然完成，不是 present packet 的字段。

## 7. Candidate 与 Decision 链路

### 7.1 两类 revision 概念

"revision"一词覆盖两个生命周期不同的概念，实现与后续文档必须区分：

| 概念 | 含义 | 失效语义 |
|---|---|---|
| `CandidateRevision` | 同一 Task 中每次 submit 形成的不可变候选尝试 | 新 submit 使旧候选不再是当前候选——**不等于作品事实被替换** |
| `ArtifactRevision` | Candidate 被 ACCEPT 并 commit 后形成的作品事实版本 | 只能被 §7.5 两阶段替换流程标记 `SUPERSEDED` |
| `DecisionRef` | 授权记录 | 绑定 Task + `CandidateRevision`，一次性消费 |
| 下游引用 | 产物间依赖 | 一律绑定 `ArtifactRevision` |

字段命名与 schema 在文档 04/06 冻结；本表冻结概念边界。

### 7.2 Candidate 提交

Agent 不写内部状态，只写 staging（§2.2）；Core 经 `submit_candidate` 原子接管：

```text
Agent 写 staging 区（任务工作包指定的可写路径，文档 06/07 冻结）
→ novelos_submit_candidate
→ Core 读取、hash、复制到内部冻结副本、分配 CandidateRevision
→ novelos_validate（对冻结 revision 的纯检查）
→ 失败：Agent 改 staging，再 submit（新 CandidateRevision）+ validate
```

每次 submit 产生新 `CandidateRevision`；旧**候选**失效仅是"不再是当前候选"，绝不触及已接受的 `ArtifactRevision`。validate 不承担写入，接口语义保持单一。正文类 Candidate 以文件传递，不经工具参数传长文本。

### 7.3 Decision 模型

三种作者决定统一为单一模型，三份文档共用词汇：

```yaml
decision:
  type: ACCEPT | REVISE | REJECT
  target_revision: 2        # CandidateRevision
  author_note: ...
```

语义：

- `ACCEPT`：记录 DecisionRef 并触发原子 commit（更新事实状态，写 events/decisions/provenance）。
- `REVISE`：Task 保持活跃，author_note 进入下一轮任务工作包，Agent 生成新 Candidate。
- `REJECT`：终止当前 Task，返回上游动作选择，不自动生成新 Candidate。

**决定值的来源**：

- **interactive（guided / assisted）**：`novelos_decide` 的模型可见参数中不含 `decision`；Extension 在 `execute` 内调用 `ctx.ui`（select/confirm + 备注输入）取得决定值后传 Core。assisted 模式的"集中确认"是同一机制的批量呈现（一次 UI 会话处理多个 pending decision），每个决定仍单独取值、单独消费。
- **evaluation**：走独立的 `TEST_FIXTURE` 分支——决定来自显式标记来源的 fixture，不经 interactive 决定入口注册，不得用于 strict-real Pilot（§9）。
- 基于 RPC UI 的 decide 路径保留给 Phase 4+ 桌面集成，届时单独冻结信任论证。

CLI 形态（示意语法，非冻结接口；语法与 launcher 见文档 04）：

```bash
python -m novelos status --json
python -m novelos task open <task-id> --json
python -m novelos candidate submit <task-id> --json
python -m novelos validate <task-id> --revision 2 --json
python -m novelos decide <task-id> --revision 2 --nonce <nonce> --decision accept --json   # --nonce/--decision 由 Extension 传入
python -m novelos checkpoint --json
```

### 7.4 Commit 授权

`novelos_present` 时 Core 生成 pending decision（含一次性 nonce，绑定 task + CandidateRevision + `candidate_content_hash`）；`decide` 必须消费该 pending 状态并携带 nonce，否则 Core 拒绝。decide 与 commit 前 Core 重验冻结候选内容 hash 与 pending 值一致，失配返回 `CANDIDATE_TAMPERED` 并拒绝提交（防确认与 commit 之间冻结候选被带外修改的 TOCTOU）。**ACCEPT commit 必须携带有效 DecisionRef；未绑定 DecisionRef 的 commit 在 Core 层被拒绝**（负向断言属 G0 工程测试；运行证据核验属 G1，见文档 03）。

### 7.5 已接受产物的两阶段替换（替换集合原子切换）

对已接受产物的修改（如文档 03 §5 场景）是**替换集合**操作：Change Task 声明 `targets` 集合（一个或多个 ArtifactRevision），新旧版本只在作者对**整集**接受时原子切换，保证任何时刻存在有效基线：

```text
阶段一：准备替换
→ 创建 Change Task（replacement.targets，如 ch-02-plan@1 + ch-02-text@1），Core 计算 impact
→ 受影响下游（如第 3 章规划）锁定：legal_actions 排除基于待替换产物的新工作
→ 集合内全部旧 ArtifactRevision 保持 ACCEPTED（当前版本），不标记 SUPERSEDED
→ Agent 按目标分别生成新候选并各自 validate；全部通过后 replacement.phase = READY_TO_SWITCH

阶段二：作者对整集一次决定
→ present 展示整个替换集合（各新候选 + fact changes + impact）
→ ACCEPT：一个事务内——集合内全部新版本成为当前版本、全部旧版本同时 SUPERSEDED、
   状态投影重生成、下游解锁、replacement.phase = COMPLETED
→ REJECT / 失败：丢弃全部新候选，旧基线全程保持，下游解锁，replacement.phase = CANCELLED
```

**失败与取消安全**：切换是整集原子事务，不产生"部分接受"的中间状态，取消无需 rollback——分步 ACCEPT 会破坏"旧基线全程有效"承诺，故不采用。单产物修改是退化替换集合（targets 长 1），机制相同。这是架构级事务约束，文档 06 在其上冻结存储格式，文档 07 冻结任务字段与按目标输出契约。

### 7.6 安全语义（诚实声明）

DecisionRef + UI 中介共同防御的是：**遵循 NovelOS 工具协议的 Agent 在未完成交互确认流程时提交**。具体保障：

- 模型无法提供决定值（`decide` 的参数 schema 不含 `decision`，L1 断言）；
- 无 pending 状态的 decide 被 Core 拒绝（L0 断言）；
- nonce 保证顺序（present 先于 decide）、一次性消费、task + CandidateRevision 绑定；
- 全部决定写入 `events.jsonl`（来源 `INTERACTIVE_UI` 与 session id），Pilot 完整性核验交叉检查。

**不防御**：Agent 绕过工具协议直接调用内部 CLI（CLI 层无法区分调用者）；恶意 Extension 伪造 UI 回调——Extension 以用户完整权限运行（Pi 层前提，§13），二者均超出 2.0 威胁模型。

## 8. Python Core 边界

### 8.1 接口稳定性承诺

- 所有命令支持 `--json`，stdout 只输出单个 JSON 文档，日志走 stderr；
- 进程退出码区分：成功 / 校验失败 / 非法操作 / 内部错误；
- 校验失败返回结构化错误列表（供 Agent 自修复），而不是人类散文；
- 每次 commit 写 provenance 记录：`artifact_path`、`before_hash`、`after_hash`、`writer: NOVEL_OS_CORE`、`event_id`、`task_id`、`candidate_revision`、`decision_ref`（完整性扫描的基础，见文档 03 G1）；
- supersede 与 STALE 标记只发生在 §7.5 阶段二的同一事务内，不存在"旧版已废、新版未立"的中间状态。

### 8.2 Phase 1 命令动词集

```text
init  status  next  task  candidate submit  validate  present  decide  checkpoint  export  doctor
```

与冻结文档 01 §6 交互循环一一对应；`doctor` 属安装诊断层（§4.2）。命令语法、参数与 launcher 在文档 04 冻结。

## 9. 运行模式 → Pi 能力映射

| 模式 | 优先级 | Pi 载体 | 关键依赖 | 作者确认来源 |
|---|---|---|---|---|
| interactive | PRIMARY | Pi TUI + Extension | registerTool/registerCommand、ctx.ui、appendEntry | `INTERACTIVE_UI`（`ctx.mode === "tui"`） |
| test | REQUIRED | SDK 首选 | createAgentSession、SessionManager.inMemory、subscribe | `TEST_FIXTURE`（显式标记） |
| headless | LATER | `pi --mode rpc` | JSONL/LF 分帧、prompt/get_state | 不接受（见下） |
| web_ui | OUT_OF_SCOPE | — | — | — |

**传输 UI 能力 ≠ NovelOS 确认策略。** Pi RPC 虽暴露 UI 交互通道（`ctx.hasUI` 为 true），NovelOS 2.0 不把它视为可信作者确认入口：需要作者确认的任务只能在 interactive 模式完成，或在 evaluation 模式使用显式 decision fixture。`TEST_FIXTURE` 决定必须标记测试来源，**不得用于 strict-real Pilot**。RPC UI 作为确认入口的可能性保留给 Phase 4+ 的桌面集成，届时单独冻结信任论证。

print/JSON 模式 `hasUI` 为 false；RPC 模式对话框类方法可用、TUI 专属方法 no-op。evaluation 模式（冻结文档 01 §7）跑在 test 载体上，`fallback_allowed: false`。

## 10. 架构级测试层边界

冻结各层"验证什么 / 不验证什么"；具体工具、fixture 与执行入口在文档 10 冻结。

| 层 | 验证 | 边界 |
|---|---|---|
| L0 Core 确定性 | Task 状态机、两类 revision 生命周期、hash、validate、decide 状态机、两阶段替换事务、checkpoint、export、**无 DecisionRef 的 commit 被拒绝（负向）** | 完全不调用模型 |
| L1 CLI / Tool 契约 | Extension 参数 → Core launcher → JSON 输出稳定；退出码；分层诊断（§4.2）；**decide 的模型可见参数 schema 不含决定值（负向）** | 不含 Agent 行为 |
| L2 Agent 行为契约 | 固定 Task Package 下：读对文件、只写 staging、调用 submit/validate、遇错修复、不改内部状态、不绕过确认 | SDK/RPC 执行，允许 fixture |
| L3 Deterministic E2E | fixture candidate 走完 空项目 → init → 规划 → 章节 → 状态 → 导出 | 无真实 Agent |
| L4 Strict-real E2E | 真实 Agent、无 fallback/seeded、确认链路完整、完整性证据齐全 | Pilot 主体（文档 03 G1/G2） |
| L5 人工验收 | 产品可用性与内容连续性判断 | 不形成自动评分（文档 03 G3） |

## 11. 会话与上下文（架构级）

- 一个 StoryArc 一个规划 Session，一个 Chapter 一个生产 Session（冻结文档 01 产品承诺的架构支撑）。
- checkpoint 后两条路径：`session.compact()` 原地压缩，或经 `AgentSessionRuntime.newSession()` 开新会话，从结构化状态恢复。
- 渐进披露三层：Skill 只载当前阶段（§3.1）；Task context 由 Core 编译（文档 07/08）；完整故事文档经 Pi 文件工具按需读取。
- Token 度量与预算数值见文档 08。

## 12. 对上游文档的修正

| 上游 | 原文 | 核验 / 评审结论 |
|---|---|---|
| `docs/draft.md` §3.1 | `npm install -g @mariozechner/pi-coding-agent` | 包名过时，应为 `@earendil-works/pi-coding-agent`（[sdk][4]） |
| `docs/design.md` §九 | `/novelos` 列于 Skill 层，工具含 accept/revise | skill 命令形如 `/skill:name` 且需开关（[skills][1]），`/novelos` 改为 Extension registerCommand；accept/revise 统一为 `novelos_decide`（含 REJECT、UI 中介），补 `novelos_submit_candidate` |
| `docs/design.md` §八 | Task Package 的 `output/` 位于 `.novelos/tasks/` 内 | 与"Agent 不得修改 `.novelos/`"冲突；Candidate staging 改置于内部状态之外，Core 经 submit 接管 |
| `docs/design.md` §六 | "rev-2 创建时 rev-1 自动失效" 未区分候选与作品版本 | 区分为 CandidateRevision 失效（§7.1/§7.2）与 ArtifactRevision 受控替换（§7.5 两阶段） |
| `docs/design.md` §十一 | strict_real 含 `manual_metadata_edit: false` | 检查范围已扩至全部受管文件与任何带外写入，更名 `out_of_band_managed_write_allowed: false`（文档 03 G1） |
| `docs/design.md` §一.5 | `source_mode` 枚举四值，验收口径却含 `DETERMINISTIC_CORE` | 枚举补第五值，并明确 source_mode 仅描述内容来源（冻结文档 01 §9.1） |
| `docs/design.md` §九 | "Pi 启动时只加载 Skill 名称和描述" | 核验属实（[skills][1] "How Skills Work"） |

## 13. 风险与约束清单

1. **权限**：Extension 以用户完整系统权限运行（官方安全声明）；NovelOS Extension 只应写 staging 与经 Core 提交，此约束在 L2 测试中断言。
2. **信任门**：仅项目级 `.pi/skills|extensions` 受信任门控；用户级主落点无此门。开发落点下 init 流程需提示信任。
3. **确认策略**：无 UI 模式禁止进入需要作者确认的任务；Core 在 `decide/commit` 层强制拒绝，不依赖 Extension 自律（§9）。
4. **RPC 分帧**：任何 RPC 消费方必须自实现 LF 分帧，禁用 Node `readline`（[rpc][3] Framing）。
5. **安装完整性**：Pi 资产与 Python Core 缺一即 `/novelos` 不可用；资产缺失只能由安装器与 `doctor` 检出（§4.2），Bootstrap 测试按三层分别覆盖。
6. **Pi 版本漂移**：本文档基于 2026-07-29 的 docs/latest；Phase 1 集成时须复核 §3 全部断言，变动回写本文档并重新冻结。

## 14. 文档索引

| # | 文档 | 状态 |
|---|---|---|
| 01 | `01-PRODUCT_DEFINITION.md` | r3，已冻结 |
| 02 | `02-RUNTIME_ARCHITECTURE.md` | 本文档（r5） |
| 03 | `03-V2_PILOT_CHARTER.md` | r4，已冻结 |
| 04 | `04-PI_INTEGRATION_CONTRACT.md` | r5，待确认 |
| 05 | `05-INTERACTION_DESIGN.md` | r5，待确认 |
| 06 | `06-WORKSPACE_AND_ARTIFACT_CONTRACT.md` | r5，待确认 |
| 07 | `07-TASK_PACKAGE_CONTRACT.md` | r5，待确认 |
| 08 | `08-TOKEN_BUDGET_AND_CONTEXT_STRATEGY.md` | 已冻结（r4） |
| 09 | `09-V1_LESSONS_AND_REUSE_MATRIX.md` | 已冻结（r3） |
| 10 | `10-TEST_STRATEGY.md` | r5，待确认 |

---

[1]: https://pi.dev/docs/latest/skills "Skills · Documentation · Pi"
[2]: https://pi.dev/docs/latest/extensions "Extensions · Documentation · Pi"
[3]: https://pi.dev/docs/latest/rpc "RPC Mode · Documentation · Pi"
[4]: https://pi.dev/docs/latest/sdk "SDK · Documentation · Pi"
[5]: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/providers.md "providers.md · earendil-works/pi · GitHub"
