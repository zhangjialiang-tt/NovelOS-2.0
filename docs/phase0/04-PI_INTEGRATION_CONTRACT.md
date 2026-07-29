# NovelOS 2.0 Pi Integration Contract

> 冻结文档 04/10 · 上游输入：冻结文档 02 §4/§6/§7/§8、冻结文档 01 §6/§7 · 状态：待确认（r6）
> r2（2026-07-29）：第三轮评审——新增 `novelos_init` 与 `brief`/`target_artifact_ref` 参数、validate 领域纯语义、Candidate 存储限 Task 作用域、幂等分级与 `--request-id`、present `preview_ref`、`integrity-scan` 动词。
> r3（2026-07-29）：第四轮评审——present 返回 preview_content 与 candidate_content_hash、decide CLI 补 --nonce、request-id 持久化账本与冲突语义、新增 CANDIDATE_TAMPERED / REQUEST_ID_CONFLICT 错误码。
> r4（2026-07-29）：第五轮评审——替换集合形状落入机器契约：present 返回 `previous_artifact_revisions[]` 与逐项 `preview_content[]`，commit 返回 `artifact_revisions[]` + `transaction_id`；`target_artifact_ref` 语义为主目标，Core 确定性扩展为 `replacement.targets[]`。
> r5（2026-07-29）：第六轮评审——preview_content 项增 `artifact_id` / `base_artifact_ref`（首建为 null）、"精确目标"残留措辞改主目标，对齐 06 r5 事件锚点。
> r6（2026-07-30）：Phase 1 实现期回写（§1.1 授权）：launcher 发现链定稿为 NOVELOS_CORE 环境变量 → ~/.novelos/launcher.json（安装脚本写入 {"argv": [...]}）→ PATH `novelos` → `python -m novelos`，发现失败为 CORE_LAUNCHER_NOT_FOUND；错误码注册表补 USAGE_ERROR（退出码 4，CLI 解析层）。

本文档冻结 NovelOS 与 Pi 之间的机器接口：Core launcher 与版本握手、JSON 传输契约、全部工具的参数与结果、CLI 映射、`novelos_decide` 的 UI 中介规范、错误码注册表。Pi 能力断言不超出冻结文档 02 §3 已核验范围。

**冻结**：传输契约、工具参数/结果形状、CLI 动词与标志、错误码、UI 中介规范、版本握手协议。
**不冻结**：TypeScript 实现细节、Skill 正文、Workspace 目录与产物 schema（文档 06）、Task Package（文档 07）。

---

## 1. 传输契约

### 1.1 Core launcher

- Python Core 暴露一个可由 Extension 稳定调用的 launcher。Phase 1 定稿：Extension 发现顺序为环境变量 NOVELOS_CORE（命令串，空白切分为 argv）→ 用户级 ~/.novelos/launcher.json（安装脚本写入 {"argv": [python 绝对路径, "-m", "novelos"]}）→ PATH 中的 novelos console script → python -m novelos。解释器为安装脚本创建的 ~/.novelos/venv 内 Python（≥3.11）。
- Extension 发现顺序：环境变量 `NOVELOS_CORE`（显式覆盖）→ 安装器写入的用户级配置 → PATH 默认解析。发现失败按 §5 `CORE_LAUNCHER_NOT_FOUND` 处理。
- Extension 在 `session_start` 执行版本握手（§1.2），失败则 `/novelos` 命令与全部工具返回 `CORE_VERSION_MISMATCH` 诊断，不进入创作流程。

### 1.2 版本握手

```bash
python -m novelos version --json
```

```json
{
  "ok": true,
  "data": {
    "core_version": "0.3.1",
    "protocol_version": "1.0",
    "min_extension_version": "0.2.0"
  }
}
```

兼容策略：`protocol_version` 同主版本号视为兼容；Extension 版本低于 `min_extension_version` 时 Core 在每次调用响应中携带 `upgrade_hint`，Extension 向用户提示。

### 1.3 JSON 信封

所有命令 `--json` 输出**单个** JSON 文档到 stdout，日志只走 stderr：

```json
{
  "ok": false,
  "data": null,
  "errors": [
    {
      "code": "VALIDATION_FAILED",
      "message": "chapter_text 缺少 claims.yaml",
      "path": "work/task-007/claims.yaml",
      "hint": "按 output-contract 补齐 claims.yaml 后重新 submit"
    }
  ]
}
```

- `ok: true` 时 `errors` 为空数组；`ok: false` 时 `data` 可为部分数据（由命令自述），`errors` 至少一项。
- `errors[].hint` 面向 Agent 自修复，必须是可执行动作，不是人类散文。

### 1.4 退出码

| 码 | 语义 |
|---|---|
| 0 | 成功 |
| 1 | 校验失败（结构化 errors，Agent 可自修复） |
| 2 | 非法操作（状态机拒绝，含未授权 commit） |
| 3 | 内部错误 |
| 4 | 参数/用法错误 |
| 5 | 环境错误（launcher 依赖缺失、版本不合、Workspace 损坏） |

### 1.5 幂等与重试

按重试语义分四级：

| 级别 | 命令 | 行为 |
|---|---|---|
| 天然幂等 | `version` / `doctor` / `status` / `next` | 可任意重试 |
| 领域效果幂等 | `validate` | 重试不累积领域效果；可能重复追加 `VALIDATED` 审计记录（审计非领域写入） |
| 变更命令 | `init` / `task open` / `candidate submit` / `present` / `checkpoint` / `export` | 每次调用产生新对象/事件；安全重试需携带 `--request-id` |
| 一次性 | `decide` | 消费 nonce；重试已消费 nonce 返回 `DECISION_NONCE_CONSUMED`（退出码 2），Extension 刷新状态而非报错 |

`--request-id <uuid>`：变更命令可选标志；Core 以同一 `request_id` 为幂等键，持久化于 `.novelos/requests/<request-id>.json`（文档 06 §8）：同 command/arguments_hash 的重复调用返回原响应（不产生新事件）；同 id 不同 command 或参数返回 `REQUEST_ID_CONFLICT`（退出码 2）。Extension 为每次变更工具调用自动生成 UUID、仅在同一次传输重试时复用，不暴露给模型。Extension 不得在无 `request_id` 时盲目自动重试变更命令。

## 2. 工具总表

调用性质见冻结文档 02 §6.2。参数为 typebox 风格示意（精确 schema 随实现冻结，变更须经本文档修订）：

| 工具 | 模型可见参数 | 结果 data 主要字段 | CLI 映射 |
|---|---|---|---|
| `novelos_init` | `{ project_name? }` | initialized, workspace_root | `init` |
| `novelos_status` | `{}` | initialized, project, stage, completed[], issues[], legal_actions[] | `status` |
| `novelos_next` | `{}` | suggested_action, task_type?, subject?, reason | `next` |
| `novelos_open_task` | `{ task_type, subject?, brief?, target_artifact_ref? }` | task_id, package_path, instructions_ref, staging_path | `task open` |
| `novelos_submit_candidate` | `{ task_id }` | candidate_revision, content_hash, files[] | `candidate submit <task-id>` |
| `novelos_validate` | `{ task_id, revision? }` | valid, errors[] | `validate <task-id> [--revision N]` |
| `novelos_present` | `{ task_id, revision? }` | present_packet, preview_content[], pending_decision{ nonce, task_id, revision, candidate_content_hash } | `present <task-id> [--revision N]` |
| `novelos_decide` | `{ task_id }` **（不含决定值与 nonce）** | decision_recorded{ type, ref }, commit?{ artifact_revisions[], transaction_id, event_id }, task_status | `decide <task-id> --revision N --nonce <nonce> --decision D [--author-note S]` |
| `novelos_checkpoint` | `{ label? }` | checkpoint_id, accepted_artifact_refs[], content_hash | `checkpoint` |
| `novelos_export` | `{ format? }` | export_path, content_hash, artifact_refs[] | `export [--format F]` |

`revision?` 缺省为当前 candidate revision；`task_type` 枚举见文档 07。`brief` 承载 premise 初始想法、artifact_change 修改说明等短文本输入（长正文一律经 staging 文件，不经参数）；`target_artifact_ref` 为 Change Task 的用户请求**主目标**（`artifact@revision`），Core 据此确定性计算 `replacement.targets[]`（文档 07 §2.1）；`subject` 仅作人类可读标题。

## 3. 工具语义细则

### 3.1 status / next

`status` 是只读全量状态板数据源（冻结文档 01 §5.2）；未初始化时 `initialized: false` 且 `legal_actions` 只含 `init`，Agent 经 `novelos_init` 执行（project_name 缺省取目录名）。`next` 基于状态推导唯一建议动作与理由，供 Agent 转述；不创建任何对象。

### 3.2 open_task

Core 创建 Task 并编译任务工作包（文档 07）：写入 `.novelos/tasks/<task-id>/`，返回 `package_path`（instructions 与 context 索引位置）与 `staging_path`（`work/<task-id>/`，Agent 唯一可写目标，文档 06 §3）。`brief` 编入任务 context（premise 初始想法 / artifact_change 修改说明）。`target_artifact_ref` 是用户请求的**主目标**；Change Task 的最终替换集合由 Core 确定性扩展并写入 `replacement.targets[]`（扩展规则：主目标 ∪ 传递依赖它的当前 ACCEPTED 产物，文档 07 §2.1），Core 据此计算 impact 与下游锁定（文档 06 §2.3）。

### 3.3 submit_candidate

Core 读取 `staging_path` 全部内容 → 计算 hash → 复制为逐任务冻结副本（`.novelos/tasks/<task-id>/candidates/rev-N/`，文档 06 §4）→ 分配 `CandidateRevision`（任务内单调递增）→ 返回。Candidate 存储属 Task 作用域；旧候选失效仅是"不再是当前候选"，**绝不触及已接受的 ArtifactRevision**（冻结文档 02 §7.1）。staging 为空返回 `VALIDATION_FAILED`（退出码 1）。

### 3.4 validate

对冻结 revision 的**领域纯检查**：输出文件齐备性（按任务类型 output contract，文档 07 §5）、结构约束、输入依赖有效性（引用的 ArtifactRevision 仍为当前版本，否则 `STALE_INPUT`）。不改变 Task 生命周期状态、ArtifactRevision 与受管文件；允许把验证结果记入 CandidateRevision 元数据并追加 `VALIDATED` 审计事件（文档 06 §4/§6）——审计不是领域写入。

### 3.5 present

Core 计算确定性 present_packet 并开启 pending decision：

```yaml
present_packet:
  validation_result:
  changed_files: []
  diff_statistics: { added, removed, files }
  impacted_artifacts: []        # 受影响的下游 ArtifactRevision
  fact_changes: []              # 状态投影层面的事实变化
  previous_artifact_revisions:  # 替换类任务：被替换集合逐项
    - ch-02-plan@1
    - ch-02-text@1
  candidate_revision:
  candidate_content_hash:       # 冻结候选 bundle（全部目标）的组合 hash（文档 06 §3.2）
```

`present` 结果在 data 顶层另返回 `preview_content`：`{ artifact_id, base_artifact_ref, preview_kind: FULL_TEXT | DIFF | STRUCTURED, content }` 列表，每个目标一项（单产物任务列表长 1）；`base_artifact_ref` 为被替换的基线版本，**首次创建时为 null**（替换任务为对应旧 `artifact@revision`）；章节级体量直接入结果，Extension 不直接读内部文件。内容源是 Core 管理的冻结候选（不是 `story/` 旧版本，不是 staging 路径），Extension 按 `artifact_id` 分组逐项渲染，不向用户暴露内部路径。Core 在 present 时核验预览内容 hash 与冻结候选一致。面向作者的语义讲述由 Agent 在对话中完成，**不是 packet 字段**（冻结文档 02 §6.3）。pending decision 含一次性 `nonce`，绑定 `task_id + candidate_revision + candidate_content_hash`。

### 3.6 decide（UI 中介）

模型可见参数仅 `task_id`。Extension 执行规范：

```text
1. 守卫：ctx.hasUI 为 true 且 ctx.mode === "tui"（冻结文档 02 §9）；否则拒绝并提示切换 interactive 模式
2. 经 novelos_present（若本轮尚未 present）取得 pending_decision（nonce、candidate_content_hash）、packet 与 preview_content
3. ctx.ui.select 呈现 ACCEPT / REVISE / REJECT（附 packet 与 preview_content 逐项渲染；替换集合整集一个决定），REVISE/REJECT 追加 author_note 输入
4. 将 UI 返回值作为 --decision / --author-note，连同 pending 中的 --nonce 传入 CLI decide（二者均不暴露给模型）
5. ACCEPT：Core 在 commit 前重验冻结候选 hash == candidate_content_hash（失配 CANDIDATE_TAMPERED），返回 commit 结果（artifact_revisions[] + transaction_id + provenance event_id），Extension 呈报
```

Core 侧约束（冻结文档 02 §7.4）：无 pending 状态 → `NO_PENDING_DECISION`；nonce 不匹配/已消费 → `DECISION_NONCE_INVALID` / `DECISION_NONCE_CONSUMED`；冻结候选内容 hash 失配 → `CANDIDATE_TAMPERED`（拒绝 commit）；ACCEPT 触发原子 commit 并写 provenance（文档 06 §8）。

**evaluation 分支**：`decide <task-id> --revision N --fixture <ref> --source TEST_FIXTURE`——决定值来自显式 fixture，来源标记 `TEST_FIXTURE`，经 ref 消费 pending 而不需 --nonce；该分支由运行模式门控，strict-real 运行禁用（文档 03 G1）。

### 3.7 checkpoint / export

`checkpoint` 记录当前全部已接受 ArtifactRevision 的快照引用与整体 content_hash（文档 06 §9）。`export` 从当前已接受产物重新生成导出物到 `export/`（source_mode `DETERMINISTIC_CORE`），返回 hash；导出物可随时重建，不是事实源。

## 4. 错误码注册表（首版）

| 码 | 退出码 | 语义 |
|---|---|---|
| `NOT_INITIALIZED` | 2 | Workspace 未初始化 |
| `WORKSPACE_CORRUPT` | 5 | 内部状态损坏或 hash 账本失配 |
| `CORE_LAUNCHER_NOT_FOUND` | 5 | Extension 侧：launcher 发现失败 |
| `CORE_VERSION_MISMATCH` | 5 | 协议版本不兼容 |
| `TASK_NOT_FOUND` | 4 | task_id 不存在 |
| `ILLEGAL_OPERATION` | 2 | 状态机拒绝（含对锁定产物的操作） |
| `VALIDATION_FAILED` | 1 | Candidate 校验失败，errors 含修复提示 |
| `STALE_INPUT` | 1 | 输入依赖的 ArtifactRevision 已非当前版本 |
| `NO_PENDING_DECISION` | 2 | decide 前未 present |
| `DECISION_NONCE_INVALID` | 2 | nonce 与 pending 不匹配 |
| `DECISION_NONCE_CONSUMED` | 2 | nonce 已消费（重试情形） |
| `COMMIT_UNAUTHORIZED` | 2 | commit 未绑定有效 DecisionRef |
| `OUT_OF_BAND_WRITE_DETECTED` | 2 | 受管文件 hash 失配（带外修改） |
| `CANDIDATE_TAMPERED` | 2 | 冻结候选内容 hash 失配（确认与 commit 之间被带外修改） |
| `REQUEST_ID_CONFLICT` | 2 | 同一 request_id 携带不同 command 或参数 |
| `INTERNAL_ERROR` | 3 | 未分类内部错误 |
| USAGE_ERROR | 4 | 参数/用法错误（CLI 解析层） |

新增错误码必须经本文档修订；Agent 自修复只允许针对退出码 1。

## 5. CLI 动词集与通用标志

```text
init  status  next  task open  candidate submit  validate  present  decide
checkpoint  export  doctor  version  integrity-scan
```

通用标志：`--json`（全部命令必须支持）、`--workspace <path>`（缺省为 cwd）、`--quiet`（压缩 stderr 日志）、`--request-id <uuid>`（变更命令幂等键，§1.5）。`doctor` 属安装诊断层（冻结文档 02 §4.2）；`integrity-scan` 输出双层完整性报告（文档 06 §3.1）；两者输出同信封。

## 6. 文档索引

| # | 文档 | 状态 |
|---|---|---|
| 01–03 | 见冻结文档 01 §13 | 已冻结（02 r5、03 r4、01 r3） |
| 04 | `04-PI_INTEGRATION_CONTRACT.md` | 本文档（r6） |
| 05 | `05-INTERACTION_DESIGN.md` | r5，待确认 |
| 06 | `06-WORKSPACE_AND_ARTIFACT_CONTRACT.md` | r5，待确认 |
| 07 | `07-TASK_PACKAGE_CONTRACT.md` | r5，待确认 |
| 08 | `08-TOKEN_BUDGET_AND_CONTEXT_STRATEGY.md` | 已冻结（r4） |
| 09 | `09-V1_LESSONS_AND_REUSE_MATRIX.md` | 已冻结（r3） |
| 10 | `10-TEST_STRATEGY.md` | r5，待确认 |
