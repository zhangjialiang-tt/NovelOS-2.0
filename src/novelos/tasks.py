"""NovelOS 任务域：open-or-resume 与任务工作包（冻结文档 07 §2/§3/§6/§7/§8）。

领域函数接收 tx 缓冲写入 + 缓冲事件、返回 dict，绝不 tx.commit()（调用方负责）。
前置状态检查序逐字依计划 C3：replay → task_type → target_artifact_ref → resume → 创建前置 → 创建。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from novelos import events
from novelos.protocol import (
    EXIT_ILLEGAL,
    EXIT_USAGE,
    ILLEGAL_OPERATION,
    USAGE_ERROR,
    NovelosError,
    canonical_json,
    sha256_hex,
)
from novelos.workspace import read_yaml, replay_or_none, write_request_record

if TYPE_CHECKING:
    from novelos.transaction import WorkspaceTransaction
    from novelos.workspace import Workspace

# premise 任务唯一合法类型（Goal 2）；非终态状态集合用于 resume 探测。
_SUPPORTED_TASK_TYPE = "premise"
_ACTIVE_STATUSES = ("OPEN", "AWAITING_DECISION")

# premise output contract 八小节标题（冻结文档 07 §5 逐字；内容结构未冻结）。
_PREMISE_SECTIONS = (
    "一句话故事钩子",
    "主角是谁",
    "主角主动目标",
    "核心阻力",
    "失败代价",
    "主要读者期待",
    "结局方向",
    "尚待作者决定的问题",
)


def _arguments_hash(task_type: str | None, subject: str | None, brief: str | None, target_artifact_ref: str | None) -> str:
    """task open 参数 canonical hash（计划 C2；None 值保留入字典保 canonical 稳定）。"""
    return sha256_hex(
        canonical_json(
            {
                "task_type": task_type,
                "subject": subject,
                "brief": brief,
                "target_artifact_ref": target_artifact_ref,
            }
        )
    )


def _is_blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def _find_active_premise_task(ws: Workspace) -> dict | None:
    """扫描 tasks_dir/*/task.json，返回首个非终态 premise 任务（磁盘态）。"""
    if not ws.tasks_dir.is_dir():
        return None
    for task_dir in sorted(ws.tasks_dir.glob("task-*")):
        task_json = task_dir / "task.json"
        if not task_json.is_file():
            continue
        data = json.loads(task_json.read_text(encoding="utf-8"))
        if data.get("task_type") == _SUPPORTED_TASK_TYPE and data.get("status") in _ACTIVE_STATUSES:
            return data
    return None


def _latest_revision_guidance_ref(ws: Workspace, task_id: str) -> str | None:
    """任务包 context/revision-notes/rev-*.md 按文件名排序最后一个的工作区相对路径。"""
    notes_dir = ws.tasks_dir / task_id / "context" / "revision-notes"
    if not notes_dir.is_dir():
        return None
    notes = sorted(notes_dir.glob("rev-*.md"))
    if not notes:
        return None
    return notes[-1].relative_to(ws.root).as_posix()


def _package_result(ws: Workspace, task_id: str, *, resumed: bool, original_brief: str | None) -> dict:
    """open_task 统一返回形状（冻结文档 04 §2）。"""
    return {
        "task_id": task_id,
        "package_path": f".novelos/tasks/{task_id}",
        "staging_path": f"work/{task_id}",
        "instructions_ref": f".novelos/tasks/{task_id}/instructions.md",
        "resumed": resumed,
        "original_brief": original_brief,
        "revision_guidance_ref": _latest_revision_guidance_ref(ws, task_id),
    }


def _next_task_id(ws: Workspace) -> str:
    """task-{n:03d}：扫 tasks_dir.glob('task-*') 最大序号 + 1，空则 1。"""
    max_n = 0
    if ws.tasks_dir.is_dir():
        for task_dir in ws.tasks_dir.glob("task-*"):
            suffix = task_dir.name[len("task-") :]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))
    return f"task-{max_n + 1:03d}"


def _render_instructions(task_id: str, brief: str) -> str:
    """任务工作包说明（冻结文档 07 §6 六要素；措辞不冻结）。"""
    sections_block = "\n".join(f"{i}. `## {name}`" for i, name in enumerate(_PREMISE_SECTIONS, 1))
    return f"""# 任务工作包：确定故事核心方向（{task_id}）

## ① 任务目的

本任务的目标是确定故事核心方向，产出 PREMISE 工件（`premise.md`）。
作者接受（present→decide ACCEPT）后，Core 将其正式落盘为 `story/premise.md`。

## ② 输入

作者故事想法摘要（brief，原文引用）：

> {brief}

`context/` 目录用于存放 Core 编译入包的上下文文件。premise 为首建任务，无上游工件输入。
若处于 REVISE 轮次，`context/revision-notes/` 下最新一轮 `rev-NNN.md` 为作者修改意见，
**必须重读最新 revision-notes 后再创作**（历史意见见同目录前序文件）。

## ③ 输出契约（output contract）

在 staging 目录 `work/{task_id}/` 内写且仅写一个文件 `premise.md`，UTF-8 无 BOM、LF 行尾。
文件必须包含以下八个小节标题（逐字），每节正文非空：

{sections_block}

## ④ 校验（validate）常见错误与修复动作

- 缺少小节 → 在 premise.md 补齐该 `## 小节` 标题。
- 小节内容为空 → 填写该小节正文。
- staging 内多余文件 → 删除 `allowed_outputs`（premise.md）之外的文件。
- 文件非 UTF-8 → 以 UTF-8 无 BOM 重新保存。

## ⑤ 硬性规则

- `work/{task_id}/` 是唯一可写目录。
- 禁止触碰 `.novelos/` 与任何受管作品文件（如 `story/`、`novelos.yaml`）。
- 禁止创建或修改任何 `SKILL.md`。

## ⑥ 作者确认

创作完成后经 `present` 提交作者审阅，作者决定（ACCEPT/REVISE/REJECT）经 `decide`
的交互式 UI 对话框产生；模型不得代为选择决定值。
"""


def open_task(
    ws: Workspace,
    tx: WorkspaceTransaction,
    *,
    task_type: str | None,
    subject: str | None,
    brief: str | None,
    target_artifact_ref: str | None,
    request_id: str | None,
    session_id: str | None,
) -> dict:
    """开启或恢复 premise 任务（冻结文档 07 §2/§3/§6；计划 C3 检查序）。

    接收 tx 缓冲写入 + 事件；返回 dict，不 commit（调用方经 guarded_transaction 负责）。
    """
    arguments_hash = _arguments_hash(task_type, subject, brief, target_artifact_ref)

    # 1. replay 检查（04 §1.5 / 06 §8）：命中直接返回原响应。
    replayed = replay_or_none(ws, "task open", request_id, arguments_hash)
    if replayed is not None:
        return replayed

    # 2. task_type 守卫：Goal 2 仅 premise。
    if task_type != _SUPPORTED_TASK_TYPE:
        raise NovelosError(
            USAGE_ERROR,
            f"不支持的 task_type：{task_type!r}",
            exit_code=EXIT_USAGE,
            hint="Goal 2 仅支持 task_type: premise",
        )

    # 3. target_artifact_ref 守卫：premise 为首建任务，域拒绝（接口已接收）。
    if not _is_blank(target_artifact_ref):
        raise NovelosError(
            USAGE_ERROR,
            "premise 任务不接受 target_artifact_ref",
            exit_code=EXIT_USAGE,
            hint="premise 为首建任务，不接受 target_artifact_ref（Change Task 专属；后续 Goal 支持）",
        )

    # 4. resume 分支（先于 brief 检查）：存在非终态 premise 任务 → 返回既有包，不创建、无事件、不写 request 记录。
    active = _find_active_premise_task(ws)
    if active is not None:
        return _package_result(ws, active["task_id"], resumed=True, original_brief=active.get("brief"))

    # 5. 创建前置：premise 已接受 → 拒绝；brief 必填。
    premise_meta = ws.artifacts_dir / "premise" / "meta.yaml"
    if premise_meta.is_file():
        meta = read_yaml(premise_meta) or {}
        if isinstance(meta, dict) and meta.get("accepted"):
            raise NovelosError(
                ILLEGAL_OPERATION,
                "故事核心已确定",
                exit_code=EXIT_ILLEGAL,
                hint="故事核心已确定；修改需经后续 Goal 的替换任务",
            )
    if _is_blank(brief):
        raise NovelosError(
            USAGE_ERROR,
            "premise 任务缺少 brief",
            exit_code=EXIT_USAGE,
            hint="premise 任务需要 brief（用户故事想法摘要）；请先在对话中收集作者想法再开任务",
        )

    # 6. 创建任务工作包。
    task_id = _next_task_id(ws)
    package_rel = f".novelos/tasks/{task_id}"
    created_at = events.utc_now_iso()

    task_json = {
        "task_id": task_id,
        "task_type": _SUPPORTED_TASK_TYPE,
        "status": "OPEN",
        "subject": subject or "故事核心方向",
        "brief": brief,
        "target_artifact_ref": None,
        "replacement": None,
        "inputs": [],
        "input_hashes": {},
        "current_candidate_revision": None,
        "allowed_outputs": ["premise.md"],
        "validation_profile": "premise-v1",
        "capability_class": "CREATIVE_HIGH",
        "created_at": created_at,
    }
    tx.write(f"{package_rel}/task.json", (json.dumps(task_json, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    tx.write(f"{package_rel}/instructions.md", _render_instructions(task_id, brief).encode("utf-8"))
    tx.write(
        f"{package_rel}/context-index.json",
        (json.dumps({"task_id": task_id, "entries": []}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    tx.write(
        f"{package_rel}/metrics.json",
        (
            json.dumps(
                {
                    "task_id": task_id,
                    "context_files_read": 0,
                    "retry_count": 0,
                    "candidate_revisions": 0,
                    "input_tokens": None,
                    "output_tokens": None,
                    "cached_tokens": None,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8"),
    )
    tx.mkdir(f"{package_rel}/context")
    tx.mkdir(f"work/{task_id}")

    result = _package_result(ws, task_id, resumed=False, original_brief=brief)
    # revision_guidance_ref 于创建分支恒为 None（尚无 revision-notes；磁盘态此刻亦无）。
    result["revision_guidance_ref"] = None

    write_request_record(
        tx,
        ws,
        command="task open",
        request_id=request_id,
        arguments_hash=arguments_hash,
        response=result,
    )

    tx.anchor_event(
        type="TASK_OPENED",
        transaction_id=events.new_transaction_id(),
        task_id=task_id,
        file_changes=[],
        source_mode=None,
        session_id=session_id,
    )

    return result
