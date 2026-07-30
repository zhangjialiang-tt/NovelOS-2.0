"""L0: 决定域（present 发布 / pending 复用 / decide 三态原子提交 / nonce 历史优先 / fixture）。

前置 task + 候选 + validate 状态按契约形状经 WorkspaceTransaction 手工构造并 commit
（不 import 兄弟领域模块）。覆盖冻结文档 03 §4 G0 负向 Goal 2 子集。
"""

import json
from pathlib import Path

import pytest

from novelos import events, integrity, workspace
from novelos.decisions import decide, present
from novelos.events import utc_now_iso
from novelos.protocol import (
    CANDIDATE_TAMPERED,
    DECISION_NONCE_CONSUMED,
    DECISION_NONCE_INVALID,
    EXIT_ILLEGAL,
    EXIT_USAGE,
    ILLEGAL_OPERATION,
    NO_PENDING_DECISION,
    NovelosError,
    canonical_json,
    combine_hash,
    sha256_hex,
)
from novelos.transaction import WorkspaceTransaction
from novelos.workspace import Workspace, read_yaml
FIXTURES = Path(__file__).parent / "fixtures" / "decisions"
TASK_ID = "task-001"
PKG = f".novelos/tasks/{TASK_ID}"

# 八小节全非空的合法 premise（UTF-8/LF）。
PREMISE_VALID = (
    "## 一句话故事钩子\n记忆当铺里，人们典当记忆换钱。\n\n"
    "## 主角是谁\n当铺学徒阿洛。\n\n"
    "## 主角主动目标\n赎回自己被典当的记忆。\n\n"
    "## 核心阻力\n赎回记忆需要付出更大代价。\n\n"
    "## 失败代价\n他将永远失去关于母亲的记忆。\n\n"
    "## 主要读者期待\n揭开记忆背后的真相。\n\n"
    "## 结局方向\n阿洛选择保留痛苦但真实的记忆。\n\n"
    "## 尚待作者决定的问题\n反派动机是否成立。\n"
)


# ---------------------------------------------------------------------------
# 状态构造
# ---------------------------------------------------------------------------


def _j(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _init(tmp_path: Path) -> Workspace:
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    return Workspace(tmp_path)


_UNSET = object()


def _add_task(
    ws: Workspace,
    *,
    revision: int = 1,
    current: object = _UNSET,
    valid: bool = True,
    status: str = "OPEN",
    source_mode: str = "REAL_AGENT",
    premise_text: str = PREMISE_VALID,
) -> None:
    """手工构造 task + 候选 + validate 状态（契约形状），经事务 commit。"""
    if current is _UNSET:
        current = revision
    tx = WorkspaceTransaction(ws)
    task = {
        "task_id": TASK_ID,
        "task_type": "premise",
        "status": status,
        "subject": "故事核心方向",
        "brief": "记忆当铺",
        "target_artifact_ref": None,
        "replacement": None,
        "inputs": [],
        "input_hashes": {},
        "current_candidate_revision": current,
        "allowed_outputs": ["premise.md"],
        "validation_profile": "premise-v1",
        "capability_class": "CREATIVE_HIGH",
        "created_at": utc_now_iso(),
    }
    tx.write(f"{PKG}/task.json", (json.dumps(task, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    tx.write(f"{PKG}/instructions.md", "# 任务工作包\n\n确定故事核心方向。\n".encode("utf-8"))
    tx.write(f"{PKG}/context-index.json", json.dumps({"task_id": TASK_ID, "entries": []}).encode("utf-8"))
    tx.write(
        f"{PKG}/metrics.json",
        json.dumps(
            {
                "task_id": TASK_ID,
                "context_files_read": 0,
                "retry_count": 0,
                "candidate_revisions": 0,
                "input_tokens": None,
                "output_tokens": None,
                "cached_tokens": None,
            }
        ).encode("utf-8"),
    )
    if current is not None:
        frozen = premise_text.encode("utf-8")
        fhash = sha256_hex(frozen)
        tx.write(f"{PKG}/candidates/rev-{revision}/premise.md", frozen)
        validation = (
            {"valid": True, "errors": [], "validated_at": utc_now_iso()}
            if valid
            else {
                "valid": False,
                "errors": [{"code": "VALIDATION_FAILED", "message": "缺少小节", "hint": "补充该小节"}],
                "validated_at": utc_now_iso(),
            }
        )
        tx.write_yaml(
            f"{PKG}/candidates/rev-{revision}/meta.yaml",
            {
                "candidate_revision": revision,
                "files": [{"path": "premise.md", "hash": fhash}],
                "submitted_at": utc_now_iso(),
                "validation": validation,
                "source_mode": source_mode,
            },
        )
    tx.mkdir(f"work/{TASK_ID}")
    tx.anchor_event(
        type="TASK_OPENED",
        transaction_id=events.new_transaction_id(),
        task_id=TASK_ID,
        file_changes=[],
        source_mode=None,
    )
    tx.commit()


def _run(fn, ws, **kwargs):
    """在事务内调用领域函数并 commit（调用方负责 commit）。"""
    tx = WorkspaceTransaction(ws)
    result = fn(ws, tx, **kwargs)
    tx.commit()
    return result


def _present(ws, **kw):
    kw.setdefault("task_id", TASK_ID)
    kw.setdefault("revision", None)
    kw.setdefault("request_id", None)
    kw.setdefault("session_id", None)
    return _run(present, ws, **kw)


def _decide(ws, **kw):
    kw.setdefault("task_id", TASK_ID)
    kw.setdefault("revision", 1)
    kw.setdefault("nonce", None)
    kw.setdefault("decision", None)
    kw.setdefault("author_note", None)
    kw.setdefault("source", "INTERACTIVE_UI")
    kw.setdefault("fixture", None)
    kw.setdefault("session_id", None)
    return _run(decide, ws, **kw)


def _pending(ws) -> dict | None:
    return _j(ws.root / PKG / "pending.json")


def _task(ws) -> dict:
    return _j(ws.root / PKG / "task.json")


def _decision_lines(ws) -> list[dict]:
    if not ws.decisions.is_file():
        return []
    return [json.loads(ln) for ln in ws.decisions.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _frozen_bytes(ws, revision: int = 1) -> bytes:
    return (ws.root / PKG / "candidates" / f"rev-{revision}" / "premise.md").read_bytes()


def _assert_err(excinfo, code: str, exit_code: int) -> None:
    err = excinfo.value
    assert err.code == code
    assert err.exit_code == exit_code
    assert err.hint, "hint 必须非空"


# ---------------------------------------------------------------------------
# present
# ---------------------------------------------------------------------------


def test_present_opens_pending_and_anchors(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    before_events = len(events.read_events(ws.events))

    res = _present(ws, request_id="req-1")

    pending = _pending(ws)
    assert set(pending) == {"task_id", "candidate_revision", "candidate_content_hash", "nonce", "created_at"}
    assert pending["task_id"] == TASK_ID
    assert pending["candidate_revision"] == 1
    assert len(pending["nonce"]) == 16
    int(pending["nonce"], 16)  # 16 位 hex
    assert pending["candidate_content_hash"] == combine_hash([("premise.md", sha256_hex(_frozen_bytes(ws)))])

    # preview 全文 == 冻结字节
    assert res["preview_content"][0]["content"] == _frozen_bytes(ws).decode("utf-8")
    assert res["preview_content"][0]["artifact_id"] == "premise"
    assert res["preview_content"][0]["base_artifact_ref"] is None
    assert res["preview_content"][0]["preview_kind"] == "FULL_TEXT"
    assert res["pending_decision"] == pending
    assert res["present_packet"]["candidate_revision"] == 1
    assert res["present_packet"]["changed_files"] == ["story/premise.md"]
    assert res["present_packet"]["diff_statistics"]["added"] == len(PREMISE_VALID.splitlines())
    assert res["present_packet"]["validation_result"]["valid"] is True

    assert _task(ws)["status"] == "AWAITING_DECISION"

    evs = events.read_events(ws.events)
    assert len(evs) == before_events + 1
    last = evs[-1]
    assert last["type"] == "DECISION_PENDING_OPENED"
    assert last["decision_ref"] is None
    assert last["internal_manifest_hash"] is not None  # 锚定


def test_present_same_candidate_reuses_pending(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    first = _present(ws, request_id="req-1")
    nonce1 = first["pending_decision"]["nonce"]
    events_after_first = len(events.read_events(ws.events))
    requests_after_first = list((ws.root / ".novelos/requests").glob("*.json"))
    assert len(requests_after_first) == 1

    # 同候选再 present（不同 request_id，走 pending 复用而非 replay）
    second = _present(ws, request_id="req-2")

    assert second["pending_decision"]["nonce"] == nonce1, "同候选复用同 nonce"
    assert len(events.read_events(ws.events)) == events_after_first, "无新事件"
    assert len(list((ws.root / ".novelos/requests").glob("*.json"))) == 1, "无新 request 记录"


def test_present_after_resubmit_issues_new_nonce(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws, revision=1)
    first = _present(ws)
    nonce1 = first["pending_decision"]["nonce"]

    # 模拟 REVISE 后重提交：新增 rev-2 候选、current=2、status OPEN（rev-1 pending 仍在盘上）
    _add_task_rev2(ws)

    second = _present(ws)
    assert second["pending_decision"]["nonce"] != nonce1, "重提交后新 nonce"
    assert second["pending_decision"]["candidate_revision"] == 2
    assert _pending(ws)["candidate_revision"] == 2, "旧 pending 被替换"


def _add_task_rev2(ws: Workspace) -> None:
    tx = WorkspaceTransaction(ws)
    task = _task(ws)
    task["current_candidate_revision"] = 2
    task["status"] = "OPEN"
    tx.write(f"{PKG}/task.json", (json.dumps(task, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    frozen = (PREMISE_VALID + "\n## 补充\nrev2 内容。\n").encode("utf-8")
    fhash = sha256_hex(frozen)
    tx.write(f"{PKG}/candidates/rev-2/premise.md", frozen)
    tx.write_yaml(
        f"{PKG}/candidates/rev-2/meta.yaml",
        {
            "candidate_revision": 2,
            "files": [{"path": "premise.md", "hash": fhash}],
            "submitted_at": utc_now_iso(),
            "validation": {"valid": True, "errors": [], "validated_at": utc_now_iso()},
            "source_mode": "REAL_AGENT",
        },
    )
    tx.anchor_event(
        type="CANDIDATE_SUBMITTED",
        transaction_id=events.new_transaction_id(),
        task_id=TASK_ID,
        candidate_revision=2,
        file_changes=[],
        source_mode="REAL_AGENT",
    )
    tx.commit()


def test_present_rejects_non_current_revision(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws, revision=2, current=2)
    with pytest.raises(NovelosError) as ei:
        _present(ws, revision=1)
    _assert_err(ei, ILLEGAL_OPERATION, EXIT_ILLEGAL)


def test_present_rejects_unvalidated(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws, valid=False)
    with pytest.raises(NovelosError) as ei:
        _present(ws)
    _assert_err(ei, ILLEGAL_OPERATION, EXIT_ILLEGAL)


def test_present_rejects_no_candidate(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws, current=None)
    with pytest.raises(NovelosError) as ei:
        _present(ws)
    _assert_err(ei, ILLEGAL_OPERATION, EXIT_ILLEGAL)


def test_present_task_not_found(tmp_path):
    ws = _init(tmp_path)
    with pytest.raises(NovelosError) as ei:
        _present(ws, task_id="task-999")
    _assert_err(ei, "TASK_NOT_FOUND", EXIT_USAGE)


# ---------------------------------------------------------------------------
# decide：前置检查
# ---------------------------------------------------------------------------


def test_decide_nonce_history_takes_priority(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    p = _present(ws)["pending_decision"]
    _decide(ws, revision=1, nonce=p["nonce"], decision="ACCEPT")
    assert _task(ws)["status"] == "DONE"

    # ACCEPT 完成后以旧 nonce 再 decide → CONSUMED（不是 NO_PENDING_DECISION）
    with pytest.raises(NovelosError) as ei:
        _decide(ws, revision=1, nonce=p["nonce"], decision="ACCEPT")
    _assert_err(ei, DECISION_NONCE_CONSUMED, EXIT_ILLEGAL)


def test_decide_no_pending(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    with pytest.raises(NovelosError) as ei:
        _decide(ws, revision=1, nonce="abcdef0123456789", decision="ACCEPT")
    _assert_err(ei, NO_PENDING_DECISION, EXIT_ILLEGAL)


def test_decide_wrong_nonce(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    _present(ws)
    with pytest.raises(NovelosError) as ei:
        _decide(ws, revision=1, nonce="ffffffffffffffff", decision="ACCEPT")
    _assert_err(ei, DECISION_NONCE_INVALID, EXIT_ILLEGAL)


def test_decide_wrong_revision(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    p = _present(ws)["pending_decision"]
    with pytest.raises(NovelosError) as ei:
        _decide(ws, revision=2, nonce=p["nonce"], decision="ACCEPT")
    _assert_err(ei, DECISION_NONCE_INVALID, EXIT_ILLEGAL)


def test_decide_tampered_candidate_rejected(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    p = _present(ws)["pending_decision"]

    # 带外篡改冻结副本字节
    target = ws.root / PKG / "candidates/rev-1/premise.md"
    target.write_bytes(_frozen_bytes(ws) + "\n## 篡改\n被改动了。\n".encode("utf-8"))

    with pytest.raises(NovelosError) as ei:
        _decide(ws, revision=1, nonce=p["nonce"], decision="ACCEPT")
    _assert_err(ei, CANDIDATE_TAMPERED, EXIT_ILLEGAL)
    assert not (ws.root / "story/premise.md").exists(), "篡改拒绝后不落盘"


# ---------------------------------------------------------------------------
# decide ACCEPT 全链
# ---------------------------------------------------------------------------


def test_decide_accept_full_chain(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    p = _present(ws)["pending_decision"]
    frozen = _frozen_bytes(ws)

    res = _decide(ws, revision=1, nonce=p["nonce"], decision="ACCEPT")

    # story/premise.md == 冻结字节
    assert (ws.root / "story/premise.md").read_bytes() == frozen
    managed_hash = sha256_hex(frozen)

    # artifact meta
    meta = read_yaml(ws.root / ".novelos/artifacts/premise/meta.yaml")
    assert meta["accepted"] == 1
    assert meta["artifact_type"] == "PREMISE"
    rev1 = meta["revisions"][0]
    assert rev1["revision"] == 1
    assert rev1["content_hash"] == managed_hash
    assert rev1["source_task"] == TASK_ID
    # ledger 末条目
    ledger = read_yaml(ws.ledger)
    entry = ledger["entries"][-1]
    assert entry["path"] == "story/premise.md"
    assert entry["hash"] == managed_hash
    assert entry["blocking"] is True
    assert entry["last_artifact_revision"] == 1

    # 两事件同 transaction_id
    evs = events.read_events(ws.events)
    by_type = {e["type"]: e for e in evs}
    rec = by_type["DECISION_RECORDED"]
    committed = by_type["COMMITTED"]
    assert rec["transaction_id"] == committed["transaction_id"]
    assert res["commit"]["transaction_id"] == committed["transaction_id"]
    assert res["commit"]["event_id"] == committed["event_id"]
    assert committed["internal_manifest_hash"] is not None  # 锚定
    assert rec["internal_manifest_hash"] is None  # 非锚定

    # decisions 行自洽 + 绑定 DECISION_RECORDED + nonce == pending.nonce
    lines = _decision_lines(ws)
    assert len(lines) == 1
    line = lines[0]
    recomputed = sha256_hex(
        canonical_json({k: v for k, v in line.items() if k != "record_hash"})
    )
    assert line["record_hash"] == recomputed
    assert line["event_id"] == rec["event_id"]
    assert line["decision"] == "ACCEPT"
    assert line["consumed"] is True
    assert line["nonce"] == p["nonce"]

    # pending 消失 + DONE
    assert _pending(ws) is None
    assert _task(ws)["status"] == "DONE"
    assert res["task_status"] == "DONE"
    assert res["decision_recorded"] == {"type": "ACCEPT", "ref": f"{TASK_ID}@rev1"}
    assert res["commit"]["artifact_revisions"] == ["premise@1"]

    # 完整性
    report = integrity.scan(ws)
    assert report.chain_ok, report.chain_detail
    assert report.anchor_ok


# ---------------------------------------------------------------------------
# decide REVISE
# ---------------------------------------------------------------------------


def test_decide_revise_writes_round1(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    p = _present(ws)["pending_decision"]
    note = "把失败代价写具体"

    res = _decide(ws, revision=1, nonce=p["nonce"], decision="REVISE", author_note=note)

    note_path = ws.root / PKG / "context/revision-notes/rev-001.md"
    assert note_path.is_file()
    assert note in note_path.read_text(encoding="utf-8")

    ci = _j(ws.root / PKG / "context-index.json")
    assert len(ci["entries"]) == 1
    assert ci["entries"][0]["round"] == 1
    assert ci["entries"][0]["path"] == "context/revision-notes/rev-001.md"

    instr = (ws.root / PKG / "instructions.md").read_text(encoding="utf-8")
    assert "当前作者修改意见：context/revision-notes/rev-001.md" in instr

    assert _j(ws.root / PKG / "metrics.json")["context_files_read"] == 1
    assert _task(ws)["status"] == "OPEN"
    assert _pending(ws) is None

    line = _decision_lines(ws)[-1]
    assert line["decision"] == "REVISE"
    assert line["consumed"] is True
    assert line["author_note"] == note

    assert res["task_status"] == "OPEN"
    assert res["author_note"] == note
    assert res["revision_guidance_ref"] == f"{PKG}/context/revision-notes/rev-001.md"
    assert res["commit"] is None

    report = integrity.scan(ws)
    assert report.chain_ok, report.chain_detail
    assert report.anchor_ok


def test_decide_revise_second_round_immutable(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    p1 = _present(ws)["pending_decision"]
    _decide(ws, revision=1, nonce=p1["nonce"], decision="REVISE", author_note="第一轮意见")
    rev1_text = (ws.root / PKG / "context/revision-notes/rev-001.md").read_text(encoding="utf-8")

    # 再 present（current 仍 1，候选仍合法）→ 新 pending
    p2 = _present(ws)["pending_decision"]
    assert p2["nonce"] != p1["nonce"]
    res2 = _decide(ws, revision=1, nonce=p2["nonce"], decision="REVISE", author_note="第二轮意见")

    rev1_after = (ws.root / PKG / "context/revision-notes/rev-001.md").read_text(encoding="utf-8")
    assert rev1_after == rev1_text, "rev-001 不被覆盖"
    rev2 = ws.root / PKG / "context/revision-notes/rev-002.md"
    assert rev2.is_file()
    assert "第二轮意见" in rev2.read_text(encoding="utf-8")

    ci = _j(ws.root / PKG / "context-index.json")
    assert [e["round"] for e in ci["entries"]] == [1, 2]
    assert _j(ws.root / PKG / "metrics.json")["context_files_read"] == 2

    guidance_line = next(
        ln for ln in (ws.root / PKG / "instructions.md").read_text(encoding="utf-8").splitlines()
        if ln.startswith("当前作者修改意见：")
    )
    assert "rev-002.md" in guidance_line
    assert res2["revision_guidance_ref"] == f"{PKG}/context/revision-notes/rev-002.md"

    assert len(_decision_lines(ws)) == 2


# ---------------------------------------------------------------------------
# decide REJECT
# ---------------------------------------------------------------------------


def test_decide_reject_terminal(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    p = _present(ws)["pending_decision"]

    res = _decide(ws, revision=1, nonce=p["nonce"], decision="REJECT", author_note="放弃")

    assert _task(ws)["status"] == "REJECTED"
    assert _pending(ws) is None
    assert (ws.root / PKG / "task.json").is_file(), "包保留审计"
    assert (ws.root / "work" / TASK_ID).is_dir(), "staging 保留审计"
    assert not (ws.root / "story/premise.md").exists()

    line = _decision_lines(ws)[-1]
    assert line["decision"] == "REJECT"
    assert line["consumed"] is True
    assert res["task_status"] == "REJECTED"

    report = integrity.scan(ws)
    assert report.chain_ok, report.chain_detail
    assert report.anchor_ok


# ---------------------------------------------------------------------------
# fixture 分支
# ---------------------------------------------------------------------------


def test_decide_accept_fixture_no_nonce(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    p = _present(ws)["pending_decision"]

    res = _decide(ws, revision=1, fixture=FIXTURES / "accept-premise.json")

    assert res["task_status"] == "DONE"
    assert (ws.root / "story/premise.md").read_bytes() == _frozen_bytes(ws)
    line = _decision_lines(ws)[-1]
    assert line["source"] == "TEST_FIXTURE"
    assert line["nonce"] == p["nonce"], "fixture 内部消费 pending.nonce"
    assert line["decision"] == "ACCEPT"


def test_decide_revise_fixture_no_nonce(tmp_path):
    ws = _init(tmp_path)
    _add_task(ws)
    p = _present(ws)["pending_decision"]

    res = _decide(ws, revision=1, fixture=FIXTURES / "revise-premise.json")

    assert res["task_status"] == "OPEN"
    assert res["author_note"] == "把失败代价写具体"
    assert "把失败代价写具体" in (ws.root / PKG / "context/revision-notes/rev-001.md").read_text(encoding="utf-8")
    line = _decision_lines(ws)[-1]
    assert line["source"] == "TEST_FIXTURE"
    assert line["nonce"] == p["nonce"]
    assert line["decision"] == "REVISE"
    assert line["author_note"] == "把失败代价写具体"
