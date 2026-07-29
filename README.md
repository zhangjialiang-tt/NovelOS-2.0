# NovelOS 2.0

运行在 Pi Agent 上、以本地文件为作品事实源、由 Python 确定性内核保障一致性的交互式网文创作工作台。

## 状态

Phase 1 Runtime Foundation —— bootstrap 纵向链路可用（version/doctor/init/status/next + /novelos）；创作任务能力尚未实现。

## 仓库布局

```text
docs/phase0/            十份冻结文档，权威契约
docs/implementation/    PHASE1_PLAN.md / TRACEABILITY.md
src/novelos/            Python 确定性内核（Core）
tests/                  L0/L1/L3 测试
pi/extension/           Pi Extension（薄适配层）
pi/skill/               Pi Skill
scripts/                安装与诊断脚本
```

## 快速开始

前置：Python ≥3.11、uv、Node ≥20、已安装的 `pi`。

```bash
python scripts/install.py
cd <空作品目录> && pi
```

在 pi 中输入 `/novelos`。

## 开发

```bash
uv sync && uv run pytest -m "l0 or l1 or l3"
node --test "pi/extension/test/*.test.ts"
```

## 文档索引

- 冻结文档索引表：`docs/phase0/01-PRODUCT_DEFINITION.md` §13
- 条款—实现—测试追踪：`docs/implementation/TRACEABILITY.md`
