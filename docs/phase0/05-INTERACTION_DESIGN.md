# NovelOS 2.0 Interaction Design

> 冻结文档 05/10 · 上游输入：冻结文档 01 §5–§7、冻结文档 02 §3.2/§6/§9、冻结文档 04 §2–§4 · 状态：待确认（r5）
> r2（2026-07-29）：第三轮评审——确认前展示冻结 Candidate（preview_ref）而非旧正文、assisted 批次依赖闭包规则、/novelos 与 /novelos-status 数据源区分。
> r3（2026-07-29）：第四轮评审——预览内容改由 present 结果的 preview_content 承载（Extension 不直接读内部文件），对齐 04 r3。
> r4（2026-07-29）：第五轮评审——多产物预览与旧版本列表逐项渲染，对齐 04 r4 替换集合形状。
> r5（2026-07-29）：第六轮评审——预览按 artifact_id 分组渲染，首建（base_artifact_ref 为 null）与替换分别呈现。

本文档冻结 NovelOS 与作者之间的交互层：入口与状态板渲染、guided/assisted 对话序列、确认节点呈现、错误恢复 UX、schema 暴露规避、无 UI 模式行为。

**冻结**：入口呈现内容、状态板四要素、guided/assisted 序列与确认时机、确认节点呈现表、错误恢复 UX、schema 规避清单、无 UI 模式规则。
**不冻结**：视觉细节、Skill 正文、Task Package（文档 07）、Token 预算（文档 08）。

---

## 1. 冻结边界

| 冻结 | 不冻结 |
|---|---|
| 三入口命令呈现内容与数据源 | TUI 组件选型、色彩、间距 |
| 状态板四要素结构 | Skill 正文措辞 |
| guided 逐步序列 + assisted 批量规则 | Task Package 结构（文档 07） |
| 确认节点呈现表（§5） | Token 数值（文档 08） |
| 错误恢复分层规则 | 测试 fixture（文档 10） |
| schema 规避禁止项 | 错误消息文案微调 |
| 无 UI 模式渲染侧规则 | |

## 2. 入口与状态板

### 2.1 命令

数据源：`/novelos` 与 `/novelos-resume` 调用 `novelos_status` + `novelos_next` 两个只读工具；`/novelos-status` 只调用 `novelos_status`。命令由 Extension `registerCommand` 注册（冻结文档 02 §6.2）。

| 命令 | 呈现 | 附加 |
|---|---|---|
| `/novelos` | 状态板 + 下一步建议 | 未初始化 → 引导 init |
| `/novelos-status` | 纯状态板（阶段/已完成/当前问题三项），只读 | 无建议动作栏 |
| `/novelos-resume` | 状态板 + 中断恢复建议 | 基于 `novelos_next` |

自然语言入口：Pi 将自然语言路由到已加载的 novelos Skill 与命令。不做更多断言。

### 2.2 状态板要素

| 要素 | 数据源字段 | 渲染 |
|---|---|---|
| 当前阶段 | `stage` | 人类可读阶段名 |
| 已完成 | `completed[]` | ✓ 前缀逐项 |
| 当前问题 | `issues[]` | 逐项；空则"无阻塞" |
| 建议动作 | `next.suggested_action` + `reason`（仅 `/novelos`、`/novelos-resume` 调用 `novelos_next` 取得） | Agent 散文转述 |

`initialized: false` 时仅展示"作品尚未初始化"+ 引导创建。

## 3. guided 模式标准对话序列

以 `chapter_text` 为例（其他类型同构）：

| # | 行为 | 用户可见 | 工具 |
|---|---|---|---|
| 1 | 查询状态 | 状态板 | `novelos_status` |
| 2 | 获取建议 | "下一步：撰写第 N 章" | `novelos_next` |
| 3 | 打开任务 | "正在准备写作任务…" | `novelos_open_task` |
| 4 | 创作 Candidate | 可含创作讨论 | Pi 文件工具 |
| 5–6 | submit + validate 循环 | **静默**（对用户无打断） | `novelos_submit_candidate` / `novelos_validate` |
| 7 | present | 渲染 packet（§3.1） | `novelos_present` |
| 8 | 决定对话框 | 三选项 UI（§3.2） | `novelos_decide`（UI 中介） |
| 9 | ACCEPT → commit 呈报 / REVISE → 回 4 / REJECT → 终止 | 结果散文 | Core commit |
| 10 | checkpoint | "进度已保存" | `novelos_checkpoint` |

**静默规则**：步骤 5–6 不产生交互打断。Agent 可简述"正在调整格式"，不展示错误码、字段名、内部路径。自修复超 3 轮升级为向用户说明。

### 3.1 present 渲染规则

packet 为确定性内容（冻结文档 04 §3.5）：

| 字段 | 渲染 |
|---|---|
| `validation_result` | ✓ 通过标记 |
| `changed_files` | 人类可读文件列表（不展示完整内部路径） |
| `diff_statistics` | "新增 X / 删除 Y / Z 个文件" |
| `impacted_artifacts` | 非空则列出；空则隐藏 |
| `fact_changes` | 非空则列出；空则隐藏 |
| `previous_artifact_revisions` | 替换类逐项列出"替换自：{旧版本列表}" |
| `preview_content[]` | **确认前按 `artifact_id` 分组逐项展示冻结 Candidate**（每项含 `preview_kind` 全文/差异与 `base_artifact_ref`——首建为 null 显示"新建"，替换显示"替换自：{基线版本}"；内容由 present 结果直接承载，源是 Core 冻结副本，不是 `story/` 旧版本）；Extension 不直接读内部文件、不暴露路径 |
| `candidate_revision` | 不向用户展示 |

语义讲述（"这章做了什么、为什么"）由 Agent 散文完成，不是 packet 字段（冻结文档 02 §6.3）。

### 3.2 decide 对话框

`ctx.ui.select` 呈现三选项：ACCEPT（保存为正式版本）/ REVISE（补充意见后重写）/ REJECT（丢弃草稿）。REVISE/REJECT 追加 `ctx.ui.input` 收集 `author_note`。决定值由 Extension 传入 CLI，模型参数不含决定值（冻结文档 04 §3.6）。替换集合的预览逐项渲染、整集一个决定；ACCEPT 后呈报 `artifact_revisions` 中的各新版本，不展示 hash。

## 4. assisted 模式

与 guided 差异**仅限确认时机**，决定取值机制相同（冻结文档 02 §7.3）：

| 维度 | guided | assisted |
|---|---|---|
| 确认时机 | 每任务完成即确认 | 检查点集中确认 |
| UI 会话 | 每 present 一次交互 | 一次会话批量呈现多个 pending decision |
| 决定取值 | 逐项 `ctx.ui.select` | 同机制，同会话内逐项取值、逐项消费 nonce |
| 默认 | ✓ | 需显式切换 |

批量规则：仅**依赖闭包互不重叠**的任务可进入同一批次；按完成顺序逐项展示 packet + 三选项；**每次决定后 Core 重新校验剩余 pending decisions**（输入依赖仍为当前版本），失效项自动退出批次并转 `BLOCKED`（或按需重新生成）；全部完成后统一 checkpoint。Phase 2 的顺序性章节链路默认使用 guided，不建设"未接受 Candidate 作为下游输入"的投机链（冻结文档 02 §7.1：下游引用只绑定 ArtifactRevision）。

## 5. 作者确认节点呈现表

按冻结文档 01 §7 节点清单：

| 节点 | 必须展示 | 不展示 |
|---|---|---|
| 故事核心方向 | 方向全文 + Agent 解读 | task_id |
| 完整故事结局 | 结局摘要 + 收束方式 | hash、revision 编号 |
| 卷级结构 | 卷划分 + 各卷目标 | 内部路径 |
| 主角核心弧光 | 弧光描述 + 变化节点 | 字段名 |
| 关键世界规则 | 规则全文 + 约束范围 | schema 定义 |
| StoryArc | 弧光全文 + 起承转合 | 内部引用 |
| 计划重大变化 | `diff_statistics` + 变化摘要 + Agent 解读 | 旧版 hash |
| 正文定稿 | `diff_statistics` + `fact_changes` + **ACCEPT 前经 `preview_content` 展示冻结 Candidate 全文** + Agent 语义讲述 | `candidate_revision`、以 `story/` 旧版作为确认依据 |
| 已确认事实修改 | `fact_changes` 逐项 + 影响范围 + 替换集合说明（02 §7.5） | 事件 id |

通用：所有节点均展示三选项 + author_note 输入。Agent 语义讲述在对话框之前以散文完成；框内只放结构化数据。确认前全文内容来自 present 结果承载的 `preview_content`（冻结文档 04 §3.5）；ACCEPT 之后正式入口才指向 `story/` 下人类可读文件。

## 6. 错误与恢复 UX

按冻结文档 04 §1.4 退出码：

| 退出码 | Agent 行为 | 用户可见 |
|---|---|---|
| 1（校验失败） | 静默自修复：读 `errors[].hint` → 改 staging → 重 submit + validate | 无打断（≤3 轮；超出则升级） |
| 2（非法操作） | 解释 + 给合法动作 | "当前不能执行此操作。你可以：{建议}" |
| 3（内部错误） | 报告 + 建议诊断 | "系统异常，请重试或运行 `novelos doctor`" |
| 4（参数错误） | Agent 自修复；反复失败同 3 | 通常不可见 |
| 5（环境错误） | 三层诊断呈现（§6.1） | 安装/环境修复建议 |

### 6.1 退出码 5 诊断呈现

| 错误码 | 呈现 | 建议 |
|---|---|---|
| `CORE_LAUNCHER_NOT_FOUND` | "核心组件未找到" | 运行安装脚本 |
| `CORE_VERSION_MISMATCH` | "版本不兼容" | 更新安装 |
| `WORKSPACE_CORRUPT` | "作品数据异常" | `novelos doctor`；不可恢复则提示 checkpoint 恢复 |

### 6.2 特定错误码

| 错误码 | 用户呈现 |
|---|---|
| `NOT_INITIALIZED` | "还没有作品。要开始新故事吗？" → 引导 init |
| `OUT_OF_BAND_WRITE_DETECTED` | "检测到系统外修改" → 说明受影响范围；Phase 2 引导从最近 checkpoint 恢复（06 §3：拒绝并要求干净状态重跑）；Phase 3+ 经受控变更流程处理 |
| `STALE_INPUT` | "内容基于旧版本，已刷新，请重新开始" |
| `DECISION_NONCE_CONSUMED` | 不展示；Extension 静默刷新（冻结文档 04 §1.5） |

## 7. schema 暴露规避规则

服务冻结文档 03 G2（schema 泄漏 ≥1 次判负）。

### UI 禁止项

| 禁止 | 替代 |
|---|---|
| 展示 `.novelos/` 路径作为操作指引 | "系统内部"或省略 |
| 展示 `work/<task-id>/` 让用户操作 | Agent 自行读写 |
| 展示 JSON 字段名 | 人类语言（"版本""文件"） |
| 展示 hash 值 | 不展示 |
| 展示退出码/错误码枚举名 | 转译为用户动作 |
| 要求理解 `source_mode`/`DecisionRef`/`nonce` | 不出现在 UI |

### Agent 话术禁止项

| 禁止 | 替代 |
|---|---|
| "请检查 claims.yaml" | "我来检查内容完整性" |
| "STALE_INPUT" | "基于旧版本，我来刷新" |
| 解释状态机转换 | 只告知结果 |
| 提及 `events.jsonl`/`decisions.jsonl` | 不提及 |

**转译原则**：`errors[].message` 与 `errors[].hint` 面向 Agent（冻结文档 04 §1.3），不直接展示。Agent 转译为现象描述 + 用户动作（或无需动作）。

## 8. 无 UI 模式行为

### 8.1 headless（RPC / print / JSON）

- `ctx.hasUI` 为 false 或 TUI 方法 no-op（冻结文档 02 §9）。
- 需确认的任务不进入：Core 在 decide/commit 层拒绝，Extension 不变通。
- 只读操作（status、export）正常执行。
- 到达确认节点时报告"需要 interactive 模式"。

### 8.2 evaluation

- 走 `TEST_FIXTURE` 分支（冻结文档 04 §3.6）；输出标注测试来源。
- 不得用于 strict-real Pilot（冻结文档 03 G1）。
- 确认对话框不出现；决定来自 fixture。

### 8.3 模式切换提示

统一呈现："此操作需要交互式确认。请切换到 interactive 模式后重试。"不展示 `ctx.hasUI`、`ctx.mode` 等实现细节。

## 9. 文档索引

| # | 文档 | 状态 |
|---|---|---|
| 01–03 | 见冻结文档 01 §13 | 已冻结（02 r5、03 r4、01 r3） |
| 04 | `04-PI_INTEGRATION_CONTRACT.md` | r5，待确认 |
| 05 | `05-INTERACTION_DESIGN.md` | 本文档（r5） |
| 06 | `06-WORKSPACE_AND_ARTIFACT_CONTRACT.md` | r5，待确认 |
| 07 | `07-TASK_PACKAGE_CONTRACT.md` | r5，待确认 |
| 08 | `08-TOKEN_BUDGET_AND_CONTEXT_STRATEGY.md` | 已冻结（r4） |
| 09 | `09-V1_LESSONS_AND_REUSE_MATRIX.md` | 已冻结（r3） |
| 10 | `10-TEST_STRATEGY.md` | r5，待确认 |
