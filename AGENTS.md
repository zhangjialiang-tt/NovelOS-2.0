# AGENTS.md

本仓库的 Agent 工作规则。契约权威与写权限以 `docs/phase0/` 冻结文档为准。

## 1. 权威规则

- `docs/phase0/` 冻结文档是契约权威；任何契约变更只能经 ADR 或冻结文档修订版（rN 注记）。
- Agent 不得自行修改契约。
- 冻结文档 04 §1.1 授权的 launcher 回写（r6）是唯一已批准的实现期修订。

## 2. 写权限（冻结文档 02 §2.2）

- Agent 只能写 `work/<task-id>/` staging 区。
- `story/`、`state/`、`export/`、`.novelos/`、`novelos.yaml` 只由 Python Core 写入。
- 校验失败必须读 `errors[].hint` 修复后重新提交，不得绕过。
- 合法性争议以 Core 判定为准（冻结文档 02 §2.1 仲裁规则）。

## 3. 三层架构

- Pi = Agent Runtime。
- Extension = 薄适配：spawn Core、解析 JSON、渲染 UI，零领域逻辑（冻结文档 02 §6.3）。
- Python Core = 确定性状态、校验、事务、文件治理。

## 4. 开发命令

```bash
uv sync
uv run pytest -m "l0 or l1 or l3"          # 每次提交节奏（冻结文档 10 §6）
uv run python -m novelos <verb> --json --workspace <dir>
python scripts/install.py
node --test "pi/extension/test/*.test.ts"
```

## 5. 代码风格

- src layout，Python ≥3.11；运行时依赖仅 PyYAML。
- 文档中文、标识符英文。
- commit 形如 `feat(core): ...` / `docs(phase0): ...` / `test(l1): ...`（匹配既有历史风格）。

## 6. 分支模型

- `base/develop` 为集成分支。
- 每个 Goal 独立短分支 `goal/NN-*` + Draft PR（docs/prompt.md §五）。
