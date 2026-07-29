# NovelOS 2.0 Workspace and Artifact Contract

> 冻结文档 06/10 · 上游输入：冻结文档 02 §2.2/§7/§8、冻结文档 01 §12、design.md §七/§八 · 状态：待确认（r5）
> r2（2026-07-29）：第三轮评审——Candidate 存储限 Task 作用域、双层完整性模型与 hash 基线、事务级 `file_changes` 与事件 hash 链、状态投影 claims 消费显式化。
> r3（2026-07-29）：第四轮评审——replacement targets 集合化、DecisionRef 绑定 candidate_content_hash、request ledger 持久化、internal-manifest 去自引用（事件锚定）、event_hash 规范化（RFC 8785）、INITIALIZED 事件与 blocking 标志。
> r4（2026-07-29）：第五轮评审——写前扫描按 blocking 分流（blocking_mismatches / derived_dirty 并冻结 Pilot 终局规则）、run_record token 字段对齐 08 §6、request ledger 清理规则（禁止清理自身及同事务记录）。
> r5（2026-07-29）：第六轮评审——补 `TASK_OPENED` / `DECISION_PENDING_OPENED` 事件与事件锚定不变量（内部状态变更事务的末事件必锚定 internal-manifest hash）。

本文档冻结作品目录的物理与逻辑契约：Workspace 布局与写权限落地、产物模型（两类 revision 的存储形态）、Candidate 提交存储、状态投影、内部状态与事件流、provenance 与 DecisionRef 完整 schema、checkpoint 与运行记录。工具接口见文档 04，任务工作包见文档 07。

**冻结**：目录布局、写权限与双层完整性（hash 账本 + 内部 hash 链）、hash 基线、Artifact/Candidate 存储模型、产物类型与状态机、事件与 provenance schema、checkpoint/run 记录、Phase 2 覆盖范围。
**不冻结**：各产物文件的内部字段细则（随任务类型在文档 07 冻结）、导出格式（实现期）、reconcile 任务的具体流程（Phase 3+）。

---

## 1. Workspace 布局

```text
my-novel/
├─ novelos.yaml                    # 项目清单：版本、项目名、Phase 覆盖；Core 写入
├─ story/                          # 受管故事文件（人类可读，仅 Core 写入）
│  ├─ premise.md                   # 故事方向
│  ├─ plan.md                      # 简化 Story Plan
│  ├─ chapters/
│  │  └─ ch-NN/
│  │     ├─ plan.md                # ChapterPlan
│  │     └─ text.md                # 章节正文
│  ├─ arcs/                        # StoryArc（Phase 3+）
│  ├─ cast.yaml                    # 角色（Phase 3+ 完整域；Phase 2 最小内联）
│  └─ world.yaml                   # 世界规则（同上）
├─ state/                          # 状态投影（Core 生成，source_mode DETERMINISTIC_CORE）
│  ├─ current.yaml                 # 当前世界/角色/剧情状态
│  ├─ loops.yaml                   # 开放伏笔与悬念
│  └─ timeline.yaml                # 事件时间线（Phase 3+）
├─ work/                           # staging：Agent 唯一可写区域
│  └─ <task-id>/                   # 每任务输出目录（文档 07 §5 output contract）
├─ export/                         # 导出物（可重新生成，非事实源）
└─ .novelos/                       # 内部状态（用户可读，仅 Core 写入）
   ├─ tasks/<task-id>/             # task.json、package/、candidates/rev-N/（冻结副本）
   ├─ artifacts/<artifact-id>/     # meta.yaml + accepted/ 版本登记（不含候选副本）
   ├─ hash-ledger.yaml             # 受管文件 hash 账本
   ├─ internal-manifest.yaml       # 内部状态文件 hash 清单（§3.1 内部层）
   ├─ requests/<request-id>.json   # request_id 幂等账本（§8）
   ├─ decisions.jsonl
   ├─ events.jsonl                 # provenance 事件流，hash 链（§3.1、§6）
   ├─ checkpoints/<checkpoint-id>.json
   └─ runs/<run-id>/               # 运行记录与证据（§7）
```

- `story/` 与 `state/` 人类可直接阅读；**可读不等于可写**（冻结文档 01 §12）。
- Phase 2 覆盖：`novelos.yaml`、`story/premise.md`、`story/plan.md`、`story/chapters/`、`state/current.yaml`、`state/loops.yaml`、`work/`、`export/`、`.novelos/` 全部。`arcs/`、完整 `cast.yaml`/`world.yaml`、`timeline.yaml` 属 Phase 3+。

## 2. Artifact 模型

### 2.1 标识与类型

Artifact 是作品事实单元，id 为稳定 slug：`premise`、`story-plan`、`ch-NN-plan`、`ch-NN-text`、`state-current`、`state-loops`。

| 类型 | 受管文件 | Phase |
|---|---|---|
| `PREMISE` | story/premise.md | 2 |
| `STORY_PLAN` | story/plan.md | 2 |
| `CHAPTER_PLAN` | story/chapters/ch-NN/plan.md | 2 |
| `CHAPTER_TEXT` | story/chapters/ch-NN/text.md | 2 |
| `STATE_PROJECTION` | state/current.yaml, state/loops.yaml | 2 |
| `STORY_ARC` | story/arcs/*.md | 3+ |
| `CAST` / `WORLD` | story/cast.yaml, story/world.yaml | 3+（完整域） |

### 2.2 两类 revision 的存储形态

与冻结文档 02 §7.1 概念对应：

- **CandidateRevision**：存于 `.novelos/tasks/<task-id>/candidates/rev-N/`——submit 时的逐文件冻结副本 + `meta.yaml`（hash 列表、提交时间、校验结果）。Candidate 作用域属 Task：`rev-N` 在任务内单调递增，两个修改同一 artifact 的任务各有独立候选序列。新 submit 使旧候选不再是当前候选；**不改变受管文件**。
- **ArtifactRevision**：ACCEPT commit 时，候选内容写入受管文件，artifact 目录下 `meta.yaml` 登记新 ArtifactRevision（单调递增）、绑定 DecisionRef、provenance event 与源候选指针（`task_id + candidate_revision`）。`accepted` 指针指向当前版本。

### 2.3 状态机

```text
ArtifactRevision: ACCEPTED（当前，每个 artifact 至多一个）
                | SUPERSEDED（被同 artifact 的新版本原子替换）
                | STALE（上游替换使其失效，尚未重新生成/接受）
CandidateRevision: SUBMITTED → VALID | INVALID（validate 结果，可多次）
替换意图: Change Task 的 task.json `replacement` 字段（文档 07 §2.1：targets 集合、phase、blocked_downstream_refs），持久化以便崩溃恢复；不在 artifact 上；切换按整集原子发生（文档 02 §7.5）
```

下游引用（task 输入、产物间依赖）一律绑定 `artifact@revision`；Core 在 `validate` 与 `status` 时检查引用仍指向当前 ACCEPTED 版本，否则 `STALE_INPUT`（文档 04 §4）。

## 3. 写权限与 hash 账本

落地冻结文档 02 §2.2 矩阵：

- `hash-ledger.yaml` 记录每个受管文件的 `{ path, hash, last_event_id, last_artifact_revision, blocking }`。`TAMPERED` 分类保留给 `blocking: true` 失配与内部层破坏；`export/` 派生物（`blocking: false`）失配只标 `DERIVED_OUTPUT_DIRTY`（重新导出即解决；Pilot 终局规则见 §7 与文档 03 §7 失败速查 #7）。
- **每次 Core 写操作前**扫描账本：`blocking: true` 且 hash 失配 → 停止操作，返回 `OUT_OF_BAND_WRITE_DETECTED`，受影响 artifact 标记 STALE，写入事件 `OUT_OF_BAND_DETECTED`；`blocking: false` 且 hash 失配 → 不停止领域操作，标记 `DERIVED_OUTPUT_DIRTY`，后续重新生成。
- Phase 2 行为：拒绝并要求从干净状态重跑（Pilot 判负，文档 03 G1）。Phase 3+ 的 reconcile 任务流程在本文档修订版冻结。
- Agent 对 `work/<task-id>/` 之外任何路径的写入都是协议违反；L2 测试断言（文档 02 §10）。

### 3.1 双层完整性模型

冻结文档 03 G1 要求 `.novelos/` 与受管文件的带外修改都被检出，故完整性分两层：

| 层 | 覆盖 | 机制 |
|---|---|---|
| 受管作品层 | novelos.yaml、story/、state/、export/ | `hash-ledger.yaml` 逐文件 hash；写前扫描如上 |
| 内部状态层 | events.jsonl、decisions.jsonl、task/candidate（含冻结内容文件）/checkpoint 元数据、request ledger、hash-ledger | `events.jsonl` hash 链：每事件含 `event_hash`/`prev_event_hash`（genesis prev 为 64 个零），事务末事件另记 `internal_manifest_hash` 锚定清单；`decisions.jsonl` 每行绑定对应 `DECISION_RECORDED` 的 `event_id` 与记录 hash；其他内部状态文件（含 `hash-ledger.yaml`）列入 `internal-manifest.yaml` 记 hash，**清单不记录自身 hash**（避免自引用），由事件链锚定 |

`integrity-scan`（文档 04 §5）依次核验两层；任一层链断裂或 hash 失配 → `TAMPERED`。威胁模型按冻结文档 02 §7.6：检测 Agent 协议外行为、人工误操作与不经 Core 的一般修改；不声称防御恶意用户重写整个 Workspace。

### 3.2 Hash 基线

| 项 | 约定 |
|---|---|
| 算法 | SHA-256 |
| 单文件 | 对文件原始字节计算 |
| 多文件组合 | 每行 `sha256:<hex>  <POSIX 相对路径>`，按路径字节序排序，取 UTF-8/LF 文本的 SHA-256 |
| 字符串形式 | `sha256:<64位hex>` |
| 受管文本文件 | Core 一律以 LF 行尾写入；带外 CRLF 改写将哈希失配并被检出 |
| 规范化 JSON | RFC 8785（JCS）：键按字节序排序、无无谓空白、UTF-8 |
| event_hash | 事件的规范化 JSON（排除 `event_hash` 字段本身，含 `prev_event_hash` 与其他全部字段）的 SHA-256 |

## 4. Candidate 存储与 output contract

`novelos_submit_candidate`（文档 04 §3.3）流程的存储侧：

```text
work/<task-id>/            # Agent 写入（文档 07 §5 规定每任务类型文件集）
→ submit
→ .novelos/tasks/<task-id>/candidates/rev-N/   # 逐文件冻结副本（Task 作用域）
   ├─ <files...>
   └─ meta.yaml            # candidate_revision, files[{path,hash}],
                           # submitted_at, validation: null
→ validate 把结果记入 meta.yaml.validation 并追加 VALIDATED 审计事件（不改 task/artifact 状态）
→ ACCEPT commit：内容 → 受管文件；artifact 目录登记 ArtifactRevision（含源候选指针）；staging 保留至 checkpoint 后由 Core 清理
```

正文类任务输出 `draft.md` + `claims.yaml`（design.md §八：不把长正文嵌进结构化数据）；`claims.yaml` 承载该章引入/改变的事实断言，供 state 投影与校验消费。每任务类型的完整文件集在文档 07 §5 冻结。

## 5. 状态投影

`state/*.yaml` 是 Core 从已接受产物派生的投影（source_mode `DETERMINISTIC_CORE`）：

- 每次 ACCEPT commit 后，Core 消费该任务的 `claims.yaml`（文档 07 §5.2）并据以重生成受影响的投影文件（与内容写入同一事务，冻结文档 02 §8.1）；Phase 2 无模型可见的状态任务，投影更新完全由 Core 确定性完成；
- 投影文件本身是 ArtifactRevision 跟踪的受管文件（类型 STATE_PROJECTION），其 supersede 由上游 commit 驱动，不经过作者确认；
- 投影是**可重建缓存**：从已接受产物全量重算的结果必须与增量维护的结果一致（L0 断言）。

`current.yaml` / `loops.yaml` 的内部字段随章节任务 claims 在文档 07 冻结。

## 6. 事件流与 provenance schema

`events.jsonl` 追加写入，每行一个事件：

```yaml
provenance_event:
  event_id: ev-000123              # 全局单调
  event_hash:                      # 本事件 sha256（hash 链，§3.1）
  prev_event_hash:                 # 前一事件 event_hash；genesis 为 64 个零
  type: INITIALIZED | TASK_OPENED | CANDIDATE_SUBMITTED | VALIDATED
      | DECISION_PENDING_OPENED | DECISION_RECORDED | COMMITTED
      | SUPERSEDED | STALE_MARKED | REPLACEMENT_LOCKED | REPLACEMENT_UNLOCKED
      | OUT_OF_BAND_DETECTED | CHECKPOINTED | EXPORTED
  transaction_id:                  # 同一事务的事件组共享（commit + supersede + 投影再生等）
  internal_manifest_hash:          # 事务末事件必填，锚定 internal-manifest.yaml（§3.1）
  task_id:
  candidate_revision:              # 适用时
  artifact_id:                     # 适用时
  artifact_revision:               # 适用时
  file_changes:                    # 本事件全部受管文件变更
    - { path: , before_hash: , after_hash: }
  before_hash:                     # 主产物快捷字段（与 file_changes 主项一致，供文档 03 G1 速查）
  after_hash:
  writer: NOVEL_OS_CORE
  decision_ref:                    # COMMITTED 必填，见 §6.1
  source_mode:                     # 内容性事件必填（冻结文档 01 §9.1）
  session_id:
  timestamp:                       # ISO-8601
```

`SUPERSEDED` / `STALE_MARKED` 只出现在替换集合原子切换事务内（冻结文档 02 §7.5）；`REPLACEMENT_LOCKED/UNLOCKED` 标记第一阶段的下游锁定与取消/完成解锁；`INITIALIZED` 伴随 init 产生（`novelos.yaml` 与骨架目录的合法性来源）；`TASK_OPENED` / `DECISION_PENDING_OPENED` 分别是 `task open` / `present` 的内部状态变更锚点。**事件锚定不变量**：任何变更内部状态的命令，其事务顺序为——生成 id/nonce → 写 task/pending/candidate 等状态 → 写 request ledger → 更新 `internal-manifest.yaml` → 追加事务末事件（含 `internal_manifest_hash`）→ 返回响应；即每个变更命令恰有一个末事件锚定其后的清单，保证任意变更命令后立即 `integrity-scan` 一致。

### 6.1 DecisionRef schema

```yaml
decision_ref:
  task_id:
  candidate_revision:
  candidate_content_hash:          # 冻结候选多文件组合 hash（§3.2）；present/decide/commit 三处重验
  decision: ACCEPT | REVISE | REJECT
  nonce:                           # present 生成，一次性
  source: INTERACTIVE_UI | TEST_FIXTURE
  session_id:
  author_note:                     # REVISE/REJECT 建议填写
  consumed: true                   # 消费后标记
  created_at:
  consumed_at:
```

`decisions.jsonl` 是 DecisionRef 的追加日志；`consumed: true` 且与某 `COMMITTED` 事件的 `decision_ref` 相等，是 G1 `all_commits_authorized` 的核验依据（文档 03）。

## 7. Checkpoint 与运行记录

```yaml
checkpoint:                        # .novelos/checkpoints/<id>.json
  checkpoint_id:
  accepted_refs: [ "ch-01-text@3", "ch-02-plan@2", ... ]
  state_snapshot_hashes: { "state/current.yaml": ..., "state/loops.yaml": ... }
  content_hash:                    # 全部受管文件的组合 hash
  created_at:

run_record:                        # .novelos/runs/<run-id>/manifest.yaml
  run_id:
  mode: interactive | evaluation
  strict_real:                     # 文档 03 G1 五旗标快照
    fallback_allowed: false
    seeded_content_allowed: false
    out_of_band_managed_write_allowed: false
    blocked_stage_causes_failure: true
    all_commits_authorized: true
  task_ids: []
  task_token_metrics:            # 按任务聚合，字段集见文档 08 §6
  run_token_summary:             # 文档 08 §6（run_tokens / final_chars / tokens_per_accepted_1000_chars / availability）
  integrity_scan:                  # 试点结束扫描报告（文档 03 G1）
    scanned_files: 42
    blocking_mismatches: []      # 非空 → TAMPERED → G1 失败
    derived_dirty: []            # export/ 派生物；Pilot 终局必须为空（非空则重导出再扫描，仍不一致 → 失败）
  result: PASS | FAIL
  failure_codes: []
```

## 8. 内部状态最小规则

- `task.json` 字段集在文档 07 冻结；本文档只规定其存放位置与"仅 Core 写"。
- `.novelos/` 内任何文件不得被 Extension 或 Agent 直接写入；L2 断言 + G1 完整性扫描双重覆盖。
- events/decisions 为 append-only 且带 hash 链（§3.1）；链断裂或损坏即 `WORKSPACE_CORRUPT`（文档 04 §4，退出码 5）。
- `requests/<request-id>.json` 记录 `{ request_id, command, arguments_hash, response, created_at }`（文档 04 §1.5）：同 id 同 command/arguments_hash → 返回原响应；同 id 不同 command 或参数 → `REQUEST_ID_CONFLICT`（文档 04 §4）。清理规则：checkpoint N 时可清理 checkpoint N−1 之前已完成任务的 request 记录，保留 checkpoint N 自身与当前活跃任务的记录；任何命令不得清理其自身及同事务的 request 记录（否则响应丢失后的重试破坏幂等）；TTL 数值不冻结。账本列入 `internal-manifest.yaml`。

## 9. 文档索引

| # | 文档 | 状态 |
|---|---|---|
| 01–03 | 见冻结文档 01 §13 | 已冻结（02 r5、03 r4、01 r3） |
| 04 | `04-PI_INTEGRATION_CONTRACT.md` | r5，待确认 |
| 05 | `05-INTERACTION_DESIGN.md` | r5，待确认 |
| 06 | `06-WORKSPACE_AND_ARTIFACT_CONTRACT.md` | 本文档（r5） |
| 07 | `07-TASK_PACKAGE_CONTRACT.md` | r5，待确认 |
| 08 | `08-TOKEN_BUDGET_AND_CONTEXT_STRATEGY.md` | 已冻结（r4） |
| 09 | `09-V1_LESSONS_AND_REUSE_MATRIX.md` | 已冻结（r3） |
| 10 | `10-TEST_STRATEGY.md` | r5，待确认 |
