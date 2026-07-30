"""NovelOS 决定域：Pending/Decision 分离存储 + present 发布 + decide 三态原子提交。

冻结形状来源：冻结文档 04 §3.5/§3.6（present/decide 语义）、06 §6/§6.1（事件锚定 /
DecisionRef 全字段）、02 §7.3/§7.4（UI 中介 / TOCTOU 重验）、07 §8（生命周期）。

两个独立 schema，不混用空字段模拟：
- pending.json：仅 AWAITING_DECISION 期间存在，五字段 {task_id, candidate_revision,
  candidate_content_hash, nonce, created_at}；manifest 收录。
- decisions.jsonl 行（DecisionRef 全字段 + 绑定）：11 字段 DecisionRef 额外携带
  event_id（绑定 DECISION_RECORDED 事件）+ record_hash（自洽校验）。decisions.jsonl
  不在 manifest（06 §3.1 三分），经事件绑定自证。

领域函数接收 tx 缓冲写入 + 事件、返回 dict，绝不 tx.commit()（调用方负责）。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from novelos import events
from novelos.events import utc_now_iso
from novelos.protocol import (
    CANDIDATE_TAMPERED,
    DECISION_NONCE_CONSUMED,
    DECISION_NONCE_INVALID,
    EXIT_ILLEGAL,
    EXIT_USAGE,
    ILLEGAL_OPERATION,
    NO_PENDING_DECISION,
    TASK_NOT_FOUND,
    USAGE_ERROR,
    NovelosError,
    canonical_json,
    combine_hash,
    sha256_hex,
)
from novelos.workspace import read_yaml, replay_or_none, write_request_record

if TYPE_CHECKING:
    from novelos.transaction import WorkspaceTransaction
    from novelos.workspace import Workspace


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _pkg(task_id: str) -> str:
    """任务包相对路径前缀。"""
    return f".novelos/tasks/{task_id}"


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(tx: WorkspaceTransaction, rel: str, obj: object) -> str:
    """经事务写 JSON（UTF-8/LF，indent=2）；返回内容 hash。"""
    return tx.write(rel, (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _read_task(ws: Workspace, task_id: str) -> dict:
    task = _read_json(ws.root / _pkg(task_id) / "task.json")
    if task is None:
        raise NovelosError(
            TASK_NOT_FOUND,
            f"任务不存在：{task_id}",
            exit_code=EXIT_USAGE,
            hint="确认 task_id 正确；运行 novelos next 查看可开任务",
        )
    return task


def _read_candidate_meta(ws: Workspace, task_id: str, revision: int) -> dict:
    path = ws.root / _pkg(task_id) / "candidates" / f"rev-{revision}" / "meta.yaml"
    if not path.is_file():
        raise NovelosError(
            ILLEGAL_OPERATION,
            "尚无候选可发布",
            exit_code=EXIT_ILLEGAL,
            hint="先运行 candidate submit 提交候选",
        )
    return read_yaml(path) or {}


def _frozen_dir(ws: Workspace, task_id: str, revision: int) -> Path:
    return ws.root / _pkg(task_id) / "candidates" / f"rev-{revision}"


def _stored_content_hash(meta: dict) -> str:
    """以冻结副本 meta.files 登记 hash 计算组合 hash（present 发布基线）。"""
    return combine_hash([(f["path"], f["hash"]) for f in meta["files"]])


def _actual_content_hash(frozen: Path, meta: dict) -> str:
    """以冻结副本实际字节重算组合 hash（decide TOCTOU 重验，02 §7.4）。"""
    return combine_hash([(f["path"], sha256_hex((frozen / f["path"]).read_bytes())) for f in meta["files"]])


def _read_decisions(ws: Workspace) -> list[dict]:
    if not ws.decisions.is_file():
        return []
    out: list[dict] = []
    for raw in ws.decisions.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw:
            out.append(json.loads(raw))
    return out


def _append_decision_line(ws: Workspace, tx: WorkspaceTransaction, decision_ref: dict, event_id: str) -> None:
    """追加 decisions.jsonl 行（DecisionRef + event_id + record_hash），整体重写。

    record_hash = sha256_hex(canonical_json(除 record_hash 外字段))；decisions.jsonl 不在
    manifest，可直接 tx.write（06 §3.1 三分）。
    """
    line = dict(decision_ref)
    line["event_id"] = event_id
    line["record_hash"] = sha256_hex(canonical_json({k: v for k, v in line.items() if k != "record_hash"}))
    existing = ws.decisions.read_bytes() if ws.decisions.is_file() else b""
    if existing and not existing.endswith(b"\n"):
        existing += b"\n"
    tx.write(".novelos/decisions.jsonl", existing + (canonical_json(line).decode("utf-8") + "\n").encode("utf-8"))


def _build_present_packet(meta: dict, revision: int, content_hash: str, content_text: str) -> dict:
    """04 §3.5 present_packet 逐字段。"""
    return {
        "validation_result": meta.get("validation"),
        "changed_files": ["story/premise.md"],
        "diff_statistics": {"added": len(content_text.splitlines()), "removed": 0, "files": 1},
        "impacted_artifacts": [],
        "fact_changes": [],
        "previous_artifact_revisions": [],
        "candidate_revision": revision,
        "candidate_content_hash": content_hash,
    }


# ---------------------------------------------------------------------------
# present
# ---------------------------------------------------------------------------


def present(
    ws: Workspace,
    tx: WorkspaceTransaction,
    *,
    task_id: str,
    revision: int | None,
    request_id: str | None,
    session_id: str | None,
) -> dict:
    """发布候选给作者，开 pending（04 §3.5）。同候选复用 pending（竞态修复）。"""
    arguments_hash = sha256_hex(canonical_json({"task_id": task_id, "revision": revision}))
    replayed = replay_or_none(ws, "present", request_id, arguments_hash)
    if replayed is not None:
        return replayed

    task = _read_task(ws, task_id)
    current = task.get("current_candidate_revision")
    if current is None:
        raise NovelosError(
            ILLEGAL_OPERATION,
            "尚无候选可发布",
            exit_code=EXIT_ILLEGAL,
            hint="先运行 candidate submit 提交候选",
        )
    rev = revision if revision is not None else current
    if rev != current:
        raise NovelosError(
            ILLEGAL_OPERATION,
            f"只能 present 当前候选 rev-{current}",
            exit_code=EXIT_ILLEGAL,
            hint=f"改用 --revision {current}",
        )

    meta = _read_candidate_meta(ws, task_id, rev)
    validation = meta.get("validation")
    if not (isinstance(validation, dict) and validation.get("valid") is True):
        raise NovelosError(
            ILLEGAL_OPERATION,
            "候选尚未校验通过",
            exit_code=EXIT_ILLEGAL,
            hint="先运行 validate 通过后再 present",
        )

    frozen = _frozen_dir(ws, task_id, rev)
    content_hash = _stored_content_hash(meta)
    content_text = (frozen / "premise.md").read_bytes().decode("utf-8")
    packet = _build_present_packet(meta, rev, content_hash, content_text)
    preview = [
        {
            "artifact_id": "premise",
            "base_artifact_ref": None,
            "preview_kind": "FULL_TEXT",
            "content": content_text,
        }
    ]

    # pending 复用/失效：同 (revision, content_hash) → 只读返回原 pending，不写任何状态。
    pending_path = ws.root / _pkg(task_id) / "pending.json"
    existing_pending = _read_json(pending_path)
    if existing_pending is not None:
        if (
            existing_pending.get("candidate_revision") == rev
            and existing_pending.get("candidate_content_hash") == content_hash
        ):
            return {
                "present_packet": packet,
                "preview_content": preview,
                "pending_decision": existing_pending,
            }
        tx.delete_file(f"{_pkg(task_id)}/pending.json")

    pending = {
        "task_id": task_id,
        "candidate_revision": rev,
        "candidate_content_hash": content_hash,
        "nonce": uuid.uuid4().hex[:16],
        "created_at": utc_now_iso(),
    }
    _write_json(tx, f"{_pkg(task_id)}/pending.json", pending)
    task["status"] = "AWAITING_DECISION"
    _write_json(tx, f"{_pkg(task_id)}/task.json", task)

    response = {
        "present_packet": packet,
        "preview_content": preview,
        "pending_decision": pending,
    }
    write_request_record(
        tx,
        ws,
        command="present",
        request_id=request_id,
        arguments_hash=arguments_hash,
        response=response,
    )
    tx.anchor_event(
        type="DECISION_PENDING_OPENED",
        transaction_id=events.new_transaction_id(),
        task_id=task_id,
        candidate_revision=rev,
        decision_ref=None,
        file_changes=[],
        source_mode=None,
        session_id=session_id,
    )
    return response


# ---------------------------------------------------------------------------
# decide
# ---------------------------------------------------------------------------


def decide(
    ws: Workspace,
    tx: WorkspaceTransaction,
    *,
    task_id: str,
    revision: int,
    nonce: str | None,
    decision: str | None,
    author_note: str | None,
    source: str,
    fixture: str | Path | None,
    session_id: str | None,
) -> dict:
    """作者决定三态（04 §3.6）。一次性命令，不经 replay；nonce 恒消费。

    检查序：nonce 历史先于当前状态（ACCEPT 后 status 已 DONE，先查状态会误报
    NO_PENDING_DECISION）。fixture 分支（evaluation 门控由 CLI 负责）内部取 pending.nonce。
    """
    # fixture 消费：decision/author_note 取自文件，source 强制 TEST_FIXTURE，nonce 内部取。
    if fixture is not None:
        data = json.loads(Path(fixture).read_text(encoding="utf-8"))
        decision = data["decision"]
        author_note = data.get("author_note")
        source = "TEST_FIXTURE"

    # 1) nonce 历史优先（交互路径；fixture 路径 nonce 尚未确定，跳过）。
    if fixture is None:
        for line in _read_decisions(ws):
            if line.get("nonce") == nonce:
                raise NovelosError(
                    DECISION_NONCE_CONSUMED,
                    "该决定 nonce 已被消费",
                    exit_code=EXIT_ILLEGAL,
                    hint="决定为一次性；如需再次决定请重新 present 获取新 nonce",
                )

    # 2) 任务 + pending 存在。
    task = _read_task(ws, task_id)
    pending = _read_json(ws.root / _pkg(task_id) / "pending.json")
    if pending is None:
        raise NovelosError(
            NO_PENDING_DECISION,
            "没有待决定项",
            exit_code=EXIT_ILLEGAL,
            hint="先运行 present 发布候选给作者",
        )

    # 3) revision / nonce 校验。
    if revision != pending["candidate_revision"]:
        raise NovelosError(
            DECISION_NONCE_INVALID,
            "revision 与待决定项不符",
            exit_code=EXIT_ILLEGAL,
            hint=f"使用待决定 revision {pending['candidate_revision']}",
        )
    if fixture is None:
        if nonce != pending["nonce"]:
            raise NovelosError(
                DECISION_NONCE_INVALID,
                "nonce 与待决定项不符",
                exit_code=EXIT_ILLEGAL,
                hint="使用 present 返回的 nonce",
            )
    else:
        nonce = pending["nonce"]

    rev = pending["candidate_revision"]
    if decision == "ACCEPT":
        return _decide_accept(ws, tx, task, pending, rev, nonce, source, author_note, session_id)
    if decision == "REVISE":
        return _decide_revise(ws, tx, task, pending, rev, nonce, source, author_note, session_id)
    if decision == "REJECT":
        return _decide_reject(ws, tx, task, pending, rev, nonce, source, author_note, session_id)
    raise NovelosError(
        USAGE_ERROR,
        f"未知决定值：{decision}",
        exit_code=EXIT_USAGE,
        hint="decision 必须为 ACCEPT / REVISE / REJECT",
    )


def _decision_ref(
    *,
    task_id: str,
    pending: dict,
    nonce: str,
    decision: str,
    source: str,
    author_note: str | None,
    session_id: str | None,
    now: str,
) -> dict:
    """06 §6.1 DecisionRef 全字段（11 字段；consumed 恒 True，nonce 恒 == 被消费 pending）。"""
    return {
        "task_id": task_id,
        "candidate_revision": pending["candidate_revision"],
        "candidate_content_hash": pending["candidate_content_hash"],
        "nonce": nonce,
        "decision": decision,
        "source": source,
        "session_id": session_id,
        "author_note": author_note,
        "consumed": True,
        "created_at": now,
        "consumed_at": now,
    }


def _decide_accept(
    ws: Workspace,
    tx: WorkspaceTransaction,
    task: dict,
    pending: dict,
    rev: int,
    nonce: str,
    source: str,
    author_note: str | None,
    session_id: str | None,
) -> dict:
    """ACCEPT：TOCTOU 重验 + 原子 commit（02 §7.4）。两事件同一 transaction_id。"""
    task_id = task["task_id"]
    meta = _read_candidate_meta(ws, task_id, rev)
    frozen = _frozen_dir(ws, task_id, rev)
    if _actual_content_hash(frozen, meta) != pending["candidate_content_hash"]:
        raise NovelosError(
            CANDIDATE_TAMPERED,
            "冻结候选内容在决定期间被改动",
            exit_code=EXIT_ILLEGAL,
            hint="重新 submit + validate + present 后再决定",
        )

    n = len(events.read_events(ws.events))
    rec_id = events.event_id_for(n)
    commit_id = events.event_id_for(n + 1)
    txid = events.new_transaction_id()
    now = utc_now_iso()

    managed_hash = tx.write("story/premise.md", (frozen / "premise.md").read_bytes())
    decision_ref = _decision_ref(
        task_id=task_id, pending=pending, nonce=nonce, decision="ACCEPT",
        source=source, author_note=author_note, session_id=session_id, now=now,
    )

    # artifact 登记（内部 schema；decision_ref 完整，consumed True）。
    tx.write_yaml(
        ".novelos/artifacts/premise/meta.yaml",
        {
            "artifact_id": "premise",
            "artifact_type": "PREMISE",
            "managed_path": "story/premise.md",
            "accepted": 1,
            "revisions": [
                {
                    "revision": 1,
                    "content_hash": managed_hash,
                    "event_id": commit_id,
                    "source_task": task_id,
                    "source_candidate_revision": rev,
                    "decision_ref": decision_ref,
                    "accepted_at": now,
                }
            ],
        },
    )

    # hash-ledger 追加条目（整体重写）。
    ledger = read_yaml(ws.ledger) or {}
    entries = list(ledger.get("entries", []))
    entries.append(
        {
            "path": "story/premise.md",
            "hash": managed_hash,
            "last_event_id": commit_id,
            "last_artifact_revision": 1,
            "blocking": True,
        }
    )
    tx.write_yaml(".novelos/hash-ledger.yaml", {"entries": entries})

    task["status"] = "DONE"
    _write_json(tx, f"{_pkg(task_id)}/task.json", task)
    tx.delete_file(f"{_pkg(task_id)}/pending.json")
    _append_decision_line(ws, tx, decision_ref, rec_id)

    tx.append_event(
        type="DECISION_RECORDED",
        transaction_id=txid,
        task_id=task_id,
        candidate_revision=rev,
        decision_ref=decision_ref,
        file_changes=[],
        source_mode=None,
        session_id=session_id,
    )
    tx.anchor_event(
        type="COMMITTED",
        transaction_id=txid,
        task_id=task_id,
        candidate_revision=rev,
        artifact_id="premise",
        artifact_revision=1,
        file_changes=[{"path": "story/premise.md", "before_hash": None, "after_hash": managed_hash}],
        before_hash=None,
        after_hash=managed_hash,
        decision_ref=decision_ref,
        source_mode=meta.get("source_mode"),
        session_id=session_id,
    )

    return {
        "decision_recorded": {"type": "ACCEPT", "ref": f"{task_id}@rev{rev}"},
        "commit": {
            "artifact_revisions": ["premise@1"],
            "transaction_id": txid,
            "event_id": commit_id,
        },
        "task_status": "DONE",
    }


def _decide_revise(
    ws: Workspace,
    tx: WorkspaceTransaction,
    task: dict,
    pending: dict,
    rev: int,
    nonce: str,
    source: str,
    author_note: str | None,
    session_id: str | None,
) -> dict:
    """REVISE：author_note 进下一轮工作包；逐轮不可变 revision-notes（评审 P0-6）。单锚定事件。"""
    task_id = task["task_id"]
    pkg = _pkg(task_id)
    n = len(events.read_events(ws.events))
    rec_id = events.event_id_for(n)
    txid = events.new_transaction_id()
    now = utc_now_iso()

    notes_dir = ws.root / pkg / "context" / "revision-notes"
    k = (len(list(notes_dir.glob("rev-*.md"))) if notes_dir.is_dir() else 0) + 1
    note_rel = f"context/revision-notes/rev-{k:03d}.md"
    tx.write(
        f"{pkg}/{note_rel}",
        f"# 作者修改意见（第 {k} 轮）\n\n{author_note}\n{now}\n".encode("utf-8"),
    )

    # context-index 追加条目。
    ci = _read_json(ws.root / pkg / "context-index.json") or {"task_id": task_id, "entries": []}
    ci["entries"].append({"path": note_rel, "kind": "revision_note", "round": k, "created_at": now})
    _write_json(tx, f"{pkg}/context-index.json", ci)

    # instructions 指向最新一轮（替换既有「当前作者修改意见」段）。
    instr_path = ws.root / pkg / "instructions.md"
    instr = instr_path.read_text(encoding="utf-8") if instr_path.is_file() else ""
    lines = [ln for ln in instr.splitlines() if not ln.startswith("当前作者修改意见：")]
    lines.append(f"当前作者修改意见：{note_rel}（历史意见见 context/revision-notes/ 下前序文件），重读后再创作")
    tx.write(f"{pkg}/instructions.md", ("\n".join(lines) + "\n").encode("utf-8"))

    # metrics：context_files_read = context-index entries 数（08 §6）。
    metrics = _read_json(ws.root / pkg / "metrics.json") or {
        "task_id": task_id,
        "context_files_read": 0,
        "retry_count": 0,
        "candidate_revisions": 0,
        "input_tokens": None,
        "output_tokens": None,
        "cached_tokens": None,
    }
    metrics["context_files_read"] = len(ci["entries"])
    _write_json(tx, f"{pkg}/metrics.json", metrics)

    task["status"] = "OPEN"
    _write_json(tx, f"{pkg}/task.json", task)
    tx.delete_file(f"{pkg}/pending.json")

    decision_ref = _decision_ref(
        task_id=task_id, pending=pending, nonce=nonce, decision="REVISE",
        source=source, author_note=author_note, session_id=session_id, now=now,
    )
    _append_decision_line(ws, tx, decision_ref, rec_id)
    tx.anchor_event(
        type="DECISION_RECORDED",
        transaction_id=txid,
        task_id=task_id,
        candidate_revision=rev,
        decision_ref=decision_ref,
        file_changes=[],
        source_mode=None,
        session_id=session_id,
    )

    return {
        "decision_recorded": {"type": "REVISE", "ref": f"{task_id}@rev{rev}"},
        "commit": None,
        "task_status": "OPEN",
        "author_note": author_note,
        "revision_guidance_ref": f"{pkg}/{note_rel}",
    }


def _decide_reject(
    ws: Workspace,
    tx: WorkspaceTransaction,
    task: dict,
    pending: dict,
    rev: int,
    nonce: str,
    source: str,
    author_note: str | None,
    session_id: str | None,
) -> dict:
    """REJECT：终态；包与 staging 保留审计（07 §8 不清理）。单锚定事件。"""
    task_id = task["task_id"]
    pkg = _pkg(task_id)
    n = len(events.read_events(ws.events))
    rec_id = events.event_id_for(n)
    txid = events.new_transaction_id()
    now = utc_now_iso()

    task["status"] = "REJECTED"
    _write_json(tx, f"{pkg}/task.json", task)
    tx.delete_file(f"{pkg}/pending.json")

    decision_ref = _decision_ref(
        task_id=task_id, pending=pending, nonce=nonce, decision="REJECT",
        source=source, author_note=author_note, session_id=session_id, now=now,
    )
    _append_decision_line(ws, tx, decision_ref, rec_id)
    tx.anchor_event(
        type="DECISION_RECORDED",
        transaction_id=txid,
        task_id=task_id,
        candidate_revision=rev,
        decision_ref=decision_ref,
        file_changes=[],
        source_mode=None,
        session_id=session_id,
    )

    return {
        "decision_recorded": {"type": "REJECT", "ref": f"{task_id}@rev{rev}"},
        "commit": None,
        "task_status": "REJECTED",
    }
