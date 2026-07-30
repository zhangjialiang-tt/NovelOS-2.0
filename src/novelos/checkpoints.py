"""NovelOS checkpoint: 最小进度快照（冻结文档 04 §3.7 / 06 §9 / 08 §6）。

范围（Goal 2A 最小子集）：登记已接受 artifact 的 ``artifact_id@revision`` 引用、
以 hash-ledger 全量条目计算状态内容 hash、清理 DONE 任务的 staging，锚定
CHECKPOINTED 审计事件。不含 run 生命周期、run_token_summary、request ledger 清理
（均明确延后：run → Goal 6，清理 → Goal 6 之后）；checkpoint 内不跑 integrity scan
（会记录旧状态）。

领域函数接收 ``tx`` 缓冲写入 + 缓冲事件并返回 dict，绝不 ``tx.commit()``
（commit 由调用方 CLI 的 guarded_transaction 执行）。
"""

from __future__ import annotations

import json

from novelos import events
from novelos.protocol import (
    EXIT_ILLEGAL,
    NOT_INITIALIZED,
    NovelosError,
    canonical_json,
    combine_hash,
    sha256_hex,
)
from novelos.workspace import read_yaml, replay_or_none, write_request_record

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from novelos.transaction import WorkspaceTransaction
    from novelos.workspace import Workspace


def _accepted_refs(ws: Workspace) -> list[str]:
    """遍历 artifacts/*/meta.yaml → ``f"{artifact_id}@{accepted}"``（按 artifact_id 排序）。"""
    refs: list[tuple[str, str]] = []
    if ws.artifacts_dir.is_dir():
        for meta_path in sorted(ws.artifacts_dir.glob("*/meta.yaml")):
            meta = read_yaml(meta_path)
            if not isinstance(meta, dict):
                continue
            artifact_id = meta.get("artifact_id")
            accepted = meta.get("accepted")
            if artifact_id is not None and accepted is not None:
                refs.append((str(artifact_id), f"{artifact_id}@{accepted}"))
    refs.sort(key=lambda pair: pair[0])
    return [ref for _, ref in refs]


def _content_hash(ws: Workspace) -> str:
    """combine_hash(ledger entries)（06 §9；entries 序如实，combine_hash 内部按路径排序）。"""
    ledger = read_yaml(ws.ledger) if ws.ledger.is_file() else {}
    entries = ledger.get("entries", []) if isinstance(ledger, dict) else []
    return combine_hash([(entry["path"], entry["hash"]) for entry in entries])


def _next_checkpoint_id(ws: Workspace) -> str:
    """cp-{n:03d}（n = checkpoints_dir 下 cp-*.json 最大序号 + 1）。"""
    highest = 0
    if ws.checkpoints_dir.is_dir():
        for path in ws.checkpoints_dir.glob("cp-*.json"):
            try:
                seq = int(path.stem.split("-", 1)[1])
            except (IndexError, ValueError):
                continue
            highest = max(highest, seq)
    return f"cp-{highest + 1:03d}"


def checkpoint(
    ws: Workspace,
    tx: WorkspaceTransaction,
    *,
    label: str | None,
    request_id: str | None,
    session_id: str | None,
) -> dict:
    """创建最小进度快照（04 §3.7）。

    检查序：replay（command ``checkpoint``，参数字典 ``{"label"}``）命中返回 →
    要求已初始化（否则 NOT_INITIALIZED exit 2）。随后登记 accepted_refs、计算
    content_hash、写 checkpoint json、清理 DONE 任务 staging、锚定 CHECKPOINTED。
    """
    arguments_hash = sha256_hex(canonical_json({"label": label}))
    replayed = replay_or_none(ws, "checkpoint", request_id, arguments_hash)
    if replayed is not None:
        return replayed

    if not ws.is_initialized():
        raise NovelosError(
            NOT_INITIALIZED,
            "工作区未初始化",
            exit_code=EXIT_ILLEGAL,
            hint="先运行 novelos init",
        )

    accepted_refs = _accepted_refs(ws)
    content_hash = _content_hash(ws)
    checkpoint_id = _next_checkpoint_id(ws)

    payload = {
        "checkpoint_id": checkpoint_id,
        "label": label,
        "accepted_refs": accepted_refs,
        "state_snapshot_hashes": {},
        "content_hash": content_hash,
        "created_at": events.utc_now_iso(),
    }
    rel = f".novelos/checkpoints/{checkpoint_id}.json"
    tx.write(rel, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    # staging 清理（07 §8）：仅 DONE 任务删 work/<task_id>；REJECTED 保留审计，
    # OPEN/AWAITING_DECISION 保留进行中工作。
    if ws.tasks_dir.is_dir():
        for task_dir in sorted(ws.tasks_dir.glob("*")):
            task_json = task_dir / "task.json"
            if not task_json.is_file():
                continue
            task = json.loads(task_json.read_text(encoding="utf-8"))
            if task.get("status") != "DONE":
                continue
            task_id = task.get("task_id") or task_dir.name
            tx.delete_dir(f"work/{task_id}")

    response = {
        "checkpoint_id": checkpoint_id,
        "accepted_artifact_refs": accepted_refs,
        "content_hash": content_hash,
    }

    write_request_record(
        tx,
        ws,
        command="checkpoint",
        request_id=request_id,
        arguments_hash=arguments_hash,
        response=response,
    )

    # CHECKPOINTED 为脚手架/审计事件，source_mode 为 null（冻结文档 10 §3）。
    tx.anchor_event(
        type="CHECKPOINTED",
        transaction_id=events.new_transaction_id(),
        file_changes=[],
        after_hash=content_hash,
        source_mode=None,
        session_id=session_id,
    )

    return response
