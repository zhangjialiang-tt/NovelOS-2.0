"""NovelOS provenance event chain.

Frozen shapes: 冻结文档 06 §6（事件 schema）与 r5 事件锚定不变量
（任何变更内部状态的命令，其事务末事件必锚定 internal-manifest hash）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from novelos.protocol import canonical_json, sha256_hex

# genesis 事件 prev_event_hash：64 个零（冻结文档 06 §3.1）
GENESIS_PREV_HASH = "0" * 64

WRITER = "NOVEL_OS_CORE"


def new_transaction_id() -> str:
    return "tx-" + uuid.uuid4().hex[:12]


def event_id_for(index: int) -> str:
    """全局单调事件 id（0-based 索引 → ev-000001 起）。"""
    return f"ev-{index + 1:06d}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def compute_event_hash(event: dict) -> str:
    """事件规范化 JSON（排除 event_hash 自身）的 SHA-256（冻结文档 06 §3.2）。"""
    return sha256_hex(canonical_json({k: v for k, v in event.items() if k != "event_hash"}))


def read_events(events_path: Path) -> list[dict]:
    """解析 events.jsonl 全量事件；文件不存在视为空链。"""
    path = Path(events_path)
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8", newline="\n") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                out.append(json.loads(stripped))
    return out


def compose_event(
    *,
    index: int,
    prev_hash: str,
    type: str,
    transaction_id: str | None,
    internal_manifest_hash: str | None,
    file_changes: list[dict],
    task_id: str | None = None,
    candidate_revision: int | None = None,
    artifact_id: str | None = None,
    artifact_revision: int | None = None,
    before_hash: str | None = None,
    after_hash: str | None = None,
    decision_ref: dict | None = None,
    source_mode: str | None = None,
    session_id: str | None = None,
) -> dict:
    """构造一个闭合 hash 链的事件（不写盘）；字段顺序对齐冻结文档 06 §6。"""
    event = {
        "event_id": event_id_for(index),
        "event_hash": None,
        "prev_event_hash": prev_hash,
        "type": type,
        "transaction_id": transaction_id,
        "internal_manifest_hash": internal_manifest_hash,
        "task_id": task_id,
        "candidate_revision": candidate_revision,
        "artifact_id": artifact_id,
        "artifact_revision": artifact_revision,
        "file_changes": file_changes,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "writer": WRITER,
        "decision_ref": decision_ref,
        "source_mode": source_mode,
        "session_id": session_id,
        "timestamp": utc_now_iso(),
    }
    event["event_hash"] = compute_event_hash(event)
    return event


def append_event(
    ws: object,
    *,
    type: str,
    transaction_id: str | None,
    internal_manifest_hash: str | None,
    file_changes: list[dict],
    task_id: str | None = None,
    candidate_revision: int | None = None,
    artifact_id: str | None = None,
    artifact_revision: int | None = None,
    before_hash: str | None = None,
    after_hash: str | None = None,
    decision_ref: dict | None = None,
    source_mode: str | None = None,
    session_id: str | None = None,
) -> dict:
    """追加一个事件并闭合 hash 链（直接写盘路径；事务路径经 transaction.WorkspaceTransaction）。"""
    events_path: Path = ws.events  # type: ignore[attr-defined]
    existing = read_events(events_path)
    prev = existing[-1]["event_hash"] if existing else GENESIS_PREV_HASH
    event = compose_event(
        index=len(existing),
        prev_hash=prev,
        type=type,
        transaction_id=transaction_id,
        internal_manifest_hash=internal_manifest_hash,
        file_changes=file_changes,
        task_id=task_id,
        candidate_revision=candidate_revision,
        artifact_id=artifact_id,
        artifact_revision=artifact_revision,
        before_hash=before_hash,
        after_hash=after_hash,
        decision_ref=decision_ref,
        source_mode=source_mode,
        session_id=session_id,
    )
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(canonical_json(event).decode("utf-8") + "\n")
    return event


def verify_chain(events_path: Path) -> tuple[bool, str]:
    """核验 event_hash/prev_event_hash 链与 event_id 序列。"""
    path = Path(events_path)
    if not path.exists():
        return True, "no events file"
    prev = GENESIS_PREV_HASH
    with path.open("r", encoding="utf-8", newline="\n") as fh:
        for i, raw in enumerate(fh):
            line = raw.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError as exc:
                return False, f"line {i + 1}: invalid JSON ({exc})"
            expected_id = event_id_for(i)
            if ev.get("event_id") != expected_id:
                return False, f"line {i + 1}: event_id {ev.get('event_id')!r} != {expected_id!r}"
            if ev.get("prev_event_hash") != prev:
                return False, f"line {i + 1}: prev_event_hash mismatch"
            if compute_event_hash(ev) != ev.get("event_hash"):
                return False, f"line {i + 1}: event_hash mismatch"
            prev = ev["event_hash"]
    return True, "chain ok"


def last_anchored_event(events_path: Path) -> dict | None:
    """最后一个事件；调用方检查其 internal_manifest_hash 非空（r5 锚定不变量）。"""
    events = read_events(events_path)
    return events[-1] if events else None
