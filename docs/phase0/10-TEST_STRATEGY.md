# NovelOS 2.0 Test Strategy

> 冻结文档 10/10 · 上游输入：冻结文档 02 §3.4/§4.2/§10、冻结文档 03 §4/§6/§8、冻结文档 04 §1/§4/§5、冻结文档 06 §3/§6/§7 · 状态：待确认（r5）
> r2（2026-07-29）：第三轮评审——L2 分级触发节奏（每次提交只跑 L0+L1+L3）、完整性扫描器对齐 06 §3.1 双层模型、`integrity-scan` 已入 04 §5。
> r3（2026-07-29）：第四轮评审——扫描器改以 last_event_id 为权威（不限 COMMITTED；新增 INITIALIZED 事件）、逐文件核验冻结候选内容、export/ 派生物非阻断（DERIVED_OUTPUT_DIRTY）。
> r4（2026-07-29）：第五轮评审——L0 补替换集合原子性三断言（负向 + 失败注入 + 成功路径同 transaction_id）、扫描报告分 blocking_mismatches / derived_dirty、证据树字段对齐 06 §7 r4。
> r5（2026-07-29）：第六轮评审——L1 补事件锚定断言（task open / present 后立即 integrity-scan → PASS），对齐 06 r5 锚定不变量。

本文档冻结 NovelOS 2.0 测试体系的**执行机制**：各层执行器与工具选型、fixture 与 seed 策略、证据包物理布局与完整性扫描器规格、G0–G3 执行编排、测试节奏规则与成本护栏。各层"验证什么/不验证什么"的范围定义属冻结文档 02 §10，G0–G3 的通过判据属冻结文档 03 §4——本文档不重定义二者，只补其落地手段。Pi API 断言仅采用冻结文档 02 §3.4 已核验面。

**冻结**：各层执行器/工具选型、fixture 与 seed 检测策略、证据包物理布局与完整性扫描器规格、G0–G3 执行编排、测试节奏与 Phase 最小门、环境成本护栏。
**不冻结**：具体测试用例清单、CI 平台与 runner 选型、断言库版本、token 上限的具体数值（仅给建议值待校准）。

---

## 1. 冻结边界

| 维度 | 本文档冻结 | 上游已冻结（只引用） |
|---|---|---|
| 各层验证范围 | 执行器/工具/输入/禁止项（§2） | L0–L5 范围矩阵（冻结文档 02 §10） |
| 验收判据 | 执行编排与重跑规则（§5） | G0–G3 逐门判据（冻结文档 03 §4） |
| 证据包 | 物理布局 + 扫描器规格（§4） | 必含项清单（冻结文档 03 §6）、run_record schema（冻结文档 06 §7） |
| CLI | 新增 `integrity-scan` 动词（示意） | 信封/退出码/既有动词（冻结文档 04 §1.3/§1.4/§5） |
| Pi API | L2 执行器选型 | `createAgentSession`/`SessionManager.inMemory`/`subscribe`（冻结文档 02 §3.4） |

## 2. 层实现矩阵

| 层 | 执行器 / 工具 | 输入 | 断言要点 | 禁止项 |
|---|---|---|---|---|
| L0 | pytest 进程内直调 Core（无子进程） | 临时 Workspace（tmp 目录） | 冻结文档 02 §10 L0 全项；负向（冻结文档 03 §4 G0）：无有效 DecisionRef 的 commit 被拒、无 pending 的 decide 被拒；**替换集合原子性：targets 中任一候选 INVALID/缺失 → present/decide 被拒且全部旧 ArtifactRevision 仍 ACCEPTED；原子事务中途注入写入失败 → 全部目标回到事务前状态，不允许部分切换；成功路径 → 全部新 ArtifactRevision + 状态投影 + accepted 指针 + SUPERSEDED 事件共享同一 transaction_id** | 调用模型、spawn CLI、网络 |
| L1 | subprocess 驱动真实 CLI（`--json`） | 真实临时 Workspace | JSON 信封形状（冻结文档 04 §1.3）；退出码 0–5（§1.4）；`novelos_decide` 模型可见参数 schema **不含决定值**（冻结文档 04 §2/§3.6）；诊断三层成立（冻结文档 02 §4.2：安装器自检 / `doctor` / `/novelos` 运行时各检自身可观测故障）；**事件锚定：`task open` 后、`present` 后立即 `integrity-scan` → PASS**（冻结文档 06 §6 锚定不变量） | mock CLI 内部、引入 Agent 行为 |
| L2 | Pi SDK：`createAgentSession({ sessionManager: SessionManager.inMemory(), ... })`，经 `subscribe` 收集行为（冻结文档 02 §3.4） | 固定 Task Package（冻结文档 07） | 只写 `work/<task-id>/` staging、走 submit/validate 链路、遇错修复、不改 `.novelos/` 与受管文件、不绕过 present→decide 确认；Bootstrap：Extension 在而 Python Core 缺→`/novelos` 返回含安装建议的可操作诊断（冻结文档 02 §4.2/§13.5） | 将 fixture/seed 带入 strict-real 运行 |
| L3 | fixture candidate 驱动 CLI 全链路（同 L1 执行器） | 预置 fixture candidate 集 | 空项目→init→规划→章节→状态→导出全链贯通；每个 fixture candidate 的 `source_mode` 显式为 `DETERMINISTIC_FIXTURE` | 真实 Agent、真实模型调用 |
| L4 | Pilot 运行编排（真人 operator + 真实 Agent + UI 确认） | 真实作品、空项目起步 | 冻结文档 03 G1 五旗标逐项以运行证据核验；产出 run_record（冻结文档 06 §7）+ 完整性扫描报告 | fallback / seeded 内容、带外写受管文件、跳过 BLOCKED |
| L5 | 人工规程（无自动化） | 三章定稿 + 导出产物 | 冻结文档 03 G3：作者通读判定三项；角色划分——Pilot operator 须未参与设计与实现、Story author 做内容判定、Observer 记录泄漏与介入 | 形成自动文学评分 |

> L4 与 L5 不是独立于 Pilot 的"测试套件"，而是 Pilot 本身的执行视角（冻结文档 03 §8：L4↔G1+G2、L5↔G3）。

## 3. fixture 与 seed 策略

| 项 | 规则 | 检测手段 |
|---|---|---|
| fixture 标记 | 任何 fixture candidate 必须显式 `source_mode: DETERMINISTIC_FIXTURE`；`decide --fixture <ref> --source TEST_FIXTURE` 分支由运行模式门控（冻结文档 04 §3.6） | L3 断言每个 fixture 落点标记正确；strict-real 运行中出现该分支即失败 |
| strict-real 禁 fixture/seed | strict-real 运行全程禁 fixture 与 seed | run_record `strict_real` 五旗标快照（冻结文档 06 §7）+ 证据交叉核验：任一 Candidate 或定稿产物 `source_mode` 为 `FALLBACK`/`SEEDED` 即 G1 失败（冻结文档 03 §4 G1） |
| seeded 内容检测 | premise / plan / 正文在 `init` 完成后必须**不存在**；仅允许空白项目模板与系统脚手架 | init 后扫描 `story/` 与 `state/`：内容性产物存在即失败（冻结文档 03 §4 G1 `seeded_content_allowed: false`） |

## 4. 证据包布局与完整性扫描器

证据目录物理结构（冻结文档 03 §6 必含项的落地布局；run_record schema 见冻结文档 06 §7）：

```text
.novelos/runs/<run-id>/
├─ manifest.yaml          # run_record：strict_real 旗标、task_ids、task_token_metrics / run_token_summary、result（冻结文档 06 §7）
├─ events.jsonl           # 运行期事件流副本（冻结文档 06 §6）
├─ decisions.jsonl        # DecisionRef 追加日志副本（冻结文档 06 §6.1）
└─ integrity-report.yaml  # 完整性扫描报告（见下）
```

**完整性扫描器**——Core 命令 `integrity-scan`（冻结文档 04 §5；信封与退出码沿用 04 §1.3/§1.4），覆盖冻结文档 06 §3.1 双层：

1. 受管层：遍历 `hash-ledger.yaml` 覆盖的全部受管文件（冻结文档 06 §3），逐一计算当前 hash；
2. 以 `hash-ledger.last_event_id` 为权威（不限 `COMMITTED`：`novelos.yaml` 来自 `INITIALIZED`、`export/` 来自 `EXPORTED` 等），比对该事件 `file_changes[]` 中对应路径的 `after_hash`（冻结文档 06 §6）；
3. 内部状态层：核验 `events.jsonl` 的 `event_hash`/`prev_event_hash` 链（genesis 为 64 个零）与事务末事件锚定的 `internal_manifest_hash` 对 `internal-manifest.yaml`、`decisions.jsonl` 每行与 `DECISION_RECORDED` 事件的绑定，并逐文件核验冻结候选内容与 `meta.yaml.files[].hash`（不只核验候选元数据）；链断裂或失配同样记为 `TAMPERED`；
4. 失配条目记为：

```yaml
tampered_entry:
  path:
  expected_hash:      # 最后合法 commit 的 after_hash
  actual_hash:        # 扫描时实算
  last_legitimate_event:   # event_id
```

5. 结果写入 `integrity-report.yaml` 并回填 `manifest.yaml` 的 `integrity_scan.{scanned_files, blocking_mismatches, derived_dirty}`（冻结文档 06 §7）；`blocking_mismatches` 非空 → G1 失败（冻结文档 03 §7 失败速查 #2）。`export/` 派生物（`blocking: false`，文档 06 §3）失配进 `derived_dirty`，不阻断日常 Core 写入；Pilot 终局 `derived_dirty` 必须为空——非空则重新 export 再扫描，仍不一致 → G1/G3 失败。mtime 仅作辅助证据，不作主判定。

## 5. G0–G3 执行编排

| 门 | 运行哪些套件 | 触发时机 | 执行者 | 产物 |
|---|---|---|---|---|
| G0 | L0 + L1 + L3 每次提交；L2 smoke / 全套按 §6 分级触发；进入 Pilot 前 L0–L3 全套必须全绿 | 持续 + 分级（§6） | 机器（本地/CI runner） | 各层套件结果，全绿方通过 |
| G1 | L4 strict-real 纵向运行 + `integrity-scan` | Pilot 运行期 | Pilot operator 触发、Core 出证据 | run_record + provenance 链 + integrity-report |
| G2 | L4 真人场景（冻结文档 03 §5 固定修改场景） | Pilot 运行期 | Pilot operator（真人，未参与设计/实现） | schema 泄漏计数（≥1 即失败）+ Observer 记录 |
| G3 | L5 人工通读 | Pilot 收尾 | Story author | 三项人工判定结果 |

重跑规则：任一门失败即试点失败，修复后**从失败门重跑**（冻结文档 03 §4）；G0 为前置门，未全绿不得进入 G1/G2 的 Pilot 运行。

## 6. 测试节奏规则

源自 design.md §十一，冻结为硬规则：

- 每个版本里程碑**必须**包含一个从空项目开始的纵向场景（L3 fixture 链路或 L4 真实链路）；
- **禁止**"先积累大量单元测试、数月后才跑第一次 E2E"的反模式（design.md §十一：1.0 直到最后跑 E2E 才暴露 Prompt/Adapter 形状不匹配、BLOCKED 误判）；
- **L2 分级触发**（成本与覆盖平衡——L2 为真实模型行为测试，慢、贵且可能波动）：

| 触发 | 套件 |
|---|---|
| 每次提交 | L0 + L1 + L3 |
| 修改 Skill / Extension / Task Package / 交互协议 | L2 smoke |
| PR 合并前或定时 | L2 全套 |
| 进入 Pilot 前 | L0–L3 全套全绿 |

- 每 Phase 最小门：

| Phase | 最小通过门 |
|---|---|
| Phase 1（Runtime Foundation） | L0–L3 全绿 + Bootstrap 诊断项（§2 L2） |
| Phase 2（三章 Strict-Real Pilot） | G0–G3 全过（冻结文档 03 §4） |

## 7. 环境与成本护栏

- **本地优先**：L0/L1/L3 无外部依赖，必须能本地离线运行；不绑定特定 CI 平台（不冻结）。
- **L2 provider 配置**：L2 需 Pi provider 配置（属部署层，冻结文档 02 §3.5）；允许使用低成本模型执行行为契约断言——L2 验证的是 Agent 行为形状而非内容质量，非 strict-real。
- **L2 token 上限**：建议每套件设 token 预算上限（建议值待校准，非冻结），超限即判失败以遏制行为漂移与成本失控；度量口径对齐冻结文档 01 §9.2。
- **strict-real 模型选择**：L4 所用模型/thinking level 属运行配置（冻结文档 02 §3.5），由 Pilot 运行期决定，不在本文档钉死。

## 8. 待核验项

以下为本文档引入、尚未在冻结文档 02 §3 核验面内的能力，**不作既成事实断言**，Phase 1 集成时须复核并回写：

- `integrity-scan` 动词已入冻结文档 04 §5（r2）；参数形状与报告 schema 随文档 06 §3.1/§7，本文档不再另冻；
- L2 每套件 token 上限的具体数值（本文档仅给机制，数值待校准）；
- CI runner / 持续集成平台选型（明确不冻结，留待实现期）。

## 9. 文档索引

| # | 文档 | 状态 |
|---|---|---|
| 01–03 | 见冻结文档 01 §13 | 已冻结（02 r5、03 r4、01 r3） |
| 04 | `04-PI_INTEGRATION_CONTRACT.md` | r5，待确认 |
| 05 | `05-INTERACTION_DESIGN.md` | r5，待确认 |
| 06 | `06-WORKSPACE_AND_ARTIFACT_CONTRACT.md` | r5，待确认 |
| 07 | `07-TASK_PACKAGE_CONTRACT.md` | r5，待确认 |
| 08 | `08-TOKEN_BUDGET_AND_CONTEXT_STRATEGY.md` | 已冻结（r4） |
| 09 | `09-V1_LESSONS_AND_REUSE_MATRIX.md` | 已冻结（r3） |
| 10 | `10-TEST_STRATEGY.md` | 本文档（r5） |
