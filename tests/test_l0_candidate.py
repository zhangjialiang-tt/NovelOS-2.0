"""L0: candidate submit（LF 规范化、路径安全、冻结副本、负向矩阵）。

前置 task/候选状态一律经 WorkspaceTransaction 直接按契约形状构造并 commit；
不 import 兄弟领域模块。冻结文档 04 §3.3、06 §3.2/§4、07 §5。
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from novelos import events, workspace
from novelos.candidates import _check_path_safety, submit_candidate
from novelos.protocol import (
    EXIT_ILLEGAL,
    EXIT_VALIDATION,
    ILLEGAL_OPERATION,
    OUTPUT_PATH_NOT_ALLOWED,
    UNEXPECTED_OUTPUT_FILE,
    VALIDATION_FAILED,
    NovelosError,
    combine_hash,
    sha256_hex,
)
from novelos.transaction import WorkspaceTransaction
from novelos.workspace import Workspace, read_yaml

pytestmark = pytest.mark.l0

TASK_ID = "task-001"


def _write_metrics(tx, task_id):
    metrics = {
        "task_id": task_id,
        "context_files_read": 0,
        "retry_count": 0,
        "candidate_revisions": 0,
        "input_tokens": None,
        "output_tokens": None,
        "cached_tokens": None,
    }
    tx.write(
        f".novelos/tasks/{task_id}/metrics.json",
        (json.dumps(metrics, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _setup(
    tmp_path,
    *,
    status="OPEN",
    current_rev=None,
    task_id=TASK_ID,
    allowed=None,
):
    """初始化工作区并直接构造一个 premise 任务包（OPEN 默认），commit 后返回 Workspace。"""
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    ws = Workspace(tmp_path)
    task = {
        "task_id": task_id,
        "task_type": "premise",
        "status": status,
        "subject": "故事核心方向",
        "brief": "记忆当铺：人们典当记忆换钱，主角是学徒",
        "target_artifact_ref": None,
        "replacement": None,
        "inputs": [],
        "input_hashes": {},
        "current_candidate_revision": current_rev,
        "allowed_outputs": allowed or ["premise.md"],
        "validation_profile": "premise-v1",
        "capability_class": "CREATIVE_HIGH",
        "created_at": events.utc_now_iso(),
    }
    tx = WorkspaceTransaction(ws)
    tx.write(
        f".novelos/tasks/{task_id}/task.json",
        (json.dumps(task, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    _write_metrics(tx, task_id)
    tx.mkdir(f"work/{task_id}")
    tx.anchor_event(
        type="TASK_OPENED",
        transaction_id=events.new_transaction_id(),
        task_id=task_id,
        file_changes=[],
        source_mode=None,
    )
    tx.commit()
    return ws


def _write_staging(ws, content: bytes, name="premise.md", task_id=TASK_ID):
    staging = ws.root / "work" / task_id
    staging.mkdir(parents=True, exist_ok=True)
    (staging / name).write_bytes(content)


def _submit(ws, *, task_id=TASK_ID, request_id=None, source_mode="REAL_AGENT", session_id=None):
    tx = WorkspaceTransaction(ws)
    result = submit_candidate(
        ws,
        tx,
        task_id=task_id,
        request_id=request_id,
        session_id=session_id,
        source_mode=source_mode,
    )
    tx.commit()
    return result


def _last_event(ws):
    return events.read_events(ws.events)[-1]


# ---------------------------------------------------------------------------
# 规范化 + 冻结 + meta 形状
# ---------------------------------------------------------------------------


def test_crlf_normalized_to_lf_in_frozen(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"a\r\nb\r\n")
    result = _submit(ws)
    frozen = ws.tasks_dir / TASK_ID / "candidates" / "rev-1" / "premise.md"
    assert frozen.read_bytes() == b"a\nb\n", "冻结副本须 LF 规范化"
    assert result["files"] == ["premise.md"]


def test_content_hash_equals_combine_of_frozen(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"a\r\nb\r\n")
    result = _submit(ws)
    frozen = ws.tasks_dir / TASK_ID / "candidates" / "rev-1" / "premise.md"
    frozen_hash = sha256_hex(frozen.read_bytes())
    meta = read_yaml(ws.tasks_dir / TASK_ID / "candidates" / "rev-1" / "meta.yaml")
    assert meta["files"][0]["hash"] == frozen_hash
    # preview 依据的 content_hash == combine_hash(冻结 files) == ACCEPT 后 story 将用 hash
    assert result["content_hash"] == combine_hash([("premise.md", frozen_hash)])


def test_meta_shape(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"content\n")
    _submit(ws)
    meta = read_yaml(ws.tasks_dir / TASK_ID / "candidates" / "rev-1" / "meta.yaml")
    assert set(meta.keys()) == {
        "candidate_revision",
        "files",
        "submitted_at",
        "validation",
        "source_mode",
    }
    assert meta["candidate_revision"] == 1
    assert meta["files"] == [{"path": "premise.md", "hash": meta["files"][0]["hash"]}]
    assert meta["validation"] is None
    assert meta["source_mode"] == "REAL_AGENT"


def test_rev_increments(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"v1\n")
    r1 = _submit(ws)
    assert r1["candidate_revision"] == 1
    _write_staging(ws, b"v2\n")
    r2 = _submit(ws)
    assert r2["candidate_revision"] == 2
    assert (ws.tasks_dir / TASK_ID / "candidates" / "rev-1" / "premise.md").is_file()
    assert (ws.tasks_dir / TASK_ID / "candidates" / "rev-2" / "premise.md").is_file()
    task = json.loads((ws.tasks_dir / TASK_ID / "task.json").read_text(encoding="utf-8"))
    assert task["current_candidate_revision"] == 2
    assert task["status"] == "OPEN", "submit 不改 status"


def test_source_mode_recorded_real_agent(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"x\n")
    _submit(ws, source_mode="REAL_AGENT")
    assert _last_event(ws)["source_mode"] == "REAL_AGENT"
    meta = read_yaml(ws.tasks_dir / TASK_ID / "candidates" / "rev-1" / "meta.yaml")
    assert meta["source_mode"] == "REAL_AGENT"


def test_source_mode_recorded_deterministic_fixture(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"x\n")
    _submit(ws, source_mode="DETERMINISTIC_FIXTURE")
    ev = _last_event(ws)
    assert ev["type"] == "CANDIDATE_SUBMITTED"
    assert ev["source_mode"] == "DETERMINISTIC_FIXTURE"
    meta = read_yaml(ws.tasks_dir / TASK_ID / "candidates" / "rev-1" / "meta.yaml")
    assert meta["source_mode"] == "DETERMINISTIC_FIXTURE"


def test_submitted_event_anchored(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"x\n")
    _submit(ws)
    ev = _last_event(ws)
    assert ev["type"] == "CANDIDATE_SUBMITTED"
    assert ev["candidate_revision"] == 1
    assert ev["internal_manifest_hash"] is not None


# ---------------------------------------------------------------------------
# 负向矩阵
# ---------------------------------------------------------------------------


def test_empty_staging_validation_failed(tmp_path):
    ws = _setup(tmp_path)  # staging 目录存在但空
    with pytest.raises(NovelosError) as excinfo:
        _submit(ws)
    assert excinfo.value.code == VALIDATION_FAILED
    assert excinfo.value.exit_code == EXIT_VALIDATION
    assert f"work/{TASK_ID}/" in excinfo.value.hint


def test_skill_md_unexpected(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"x\n")
    _write_staging(ws, b"skill\n", name="SKILL.md")
    with pytest.raises(NovelosError) as excinfo:
        _submit(ws)
    assert excinfo.value.code == UNEXPECTED_OUTPUT_FILE
    assert excinfo.value.exit_code == EXIT_VALIDATION
    assert "SKILL.md" in excinfo.value.hint
    assert "premise.md" in excinfo.value.hint


def test_extra_md_unexpected(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"x\n")
    _write_staging(ws, b"extra\n", name="extra.md")
    with pytest.raises(NovelosError) as excinfo:
        _submit(ws)
    assert excinfo.value.code == UNEXPECTED_OUTPUT_FILE
    assert "extra.md" in excinfo.value.hint


def test_missing_premise_validation_failed(tmp_path):
    # allowed 含两个文件，staging 只提供其一 → 触发「缺失文件」分支（区别于空 staging）。
    ws = _setup(tmp_path, allowed=["premise.md", "synopsis.md"])
    _write_staging(ws, b"synopsis\n", name="synopsis.md")
    with pytest.raises(NovelosError) as excinfo:
        _submit(ws)
    assert excinfo.value.code == VALIDATION_FAILED
    assert excinfo.value.exit_code == EXIT_VALIDATION
    assert "premise.md" in excinfo.value.hint


def test_non_utf8_validation_failed(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"\xff\xfe\x00bad")
    with pytest.raises(NovelosError) as excinfo:
        _submit(ws)
    assert excinfo.value.code == VALIDATION_FAILED
    assert "UTF-8" in excinfo.value.hint


def _make_link_or_junction(staging, tmp_path):
    """在 staging 内建符号链接；无特权时退回目录联接（Windows junction，同为 reparse point）。"""
    link = staging / "badlink"
    file_target = tmp_path / "outside.txt"
    file_target.write_text("outside", encoding="utf-8")
    try:
        os.symlink(file_target, link)
        return
    except (OSError, NotImplementedError, AttributeError):
        pass
    dir_target = tmp_path / "outside_dir"
    dir_target.mkdir()
    (dir_target / "f.txt").write_text("x", encoding="utf-8")
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(dir_target)], capture_output=True
    )
    if proc.returncode != 0 or not link.exists():
        pytest.skip("符号链接与目录联接均不受支持")


def test_symlink_in_staging_not_allowed(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"x\n")
    staging = ws.root / "work" / TASK_ID
    _make_link_or_junction(staging, tmp_path)
    with pytest.raises(NovelosError) as excinfo:
        _submit(ws)
    assert excinfo.value.code == OUTPUT_PATH_NOT_ALLOWED
    assert excinfo.value.exit_code == EXIT_VALIDATION
    assert excinfo.value.hint


def test_path_safety_rejects_absolute_and_dotdot(tmp_path):
    ws = _setup(tmp_path)
    staging = ws.root / "work" / TASK_ID
    with pytest.raises(NovelosError) as excinfo:
        _check_path_safety(staging, Path("/etc/passwd"))
    assert excinfo.value.code == OUTPUT_PATH_NOT_ALLOWED
    with pytest.raises(NovelosError) as excinfo:
        _check_path_safety(staging, Path("../escape.txt"))
    assert excinfo.value.code == OUTPUT_PATH_NOT_ALLOWED
    assert excinfo.value.hint


def test_terminal_task_illegal(tmp_path):
    ws = _setup(tmp_path, status="DONE")
    _write_staging(ws, b"x\n")
    with pytest.raises(NovelosError) as excinfo:
        _submit(ws)
    assert excinfo.value.code == ILLEGAL_OPERATION
    assert excinfo.value.exit_code == EXIT_ILLEGAL


def test_awaiting_decision_illegal(tmp_path):
    ws = _setup(tmp_path, status="AWAITING_DECISION")
    _write_staging(ws, b"x\n")
    with pytest.raises(NovelosError) as excinfo:
        _submit(ws)
    assert excinfo.value.code == ILLEGAL_OPERATION
    assert excinfo.value.exit_code == EXIT_ILLEGAL


def test_task_not_found(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"x\n", task_id="task-999")
    with pytest.raises(NovelosError) as excinfo:
        _submit(ws, task_id="task-999")
    assert excinfo.value.code == "TASK_NOT_FOUND"


def test_replay_returns_stored(tmp_path):
    ws = _setup(tmp_path)
    _write_staging(ws, b"x\n")
    req = "req-1"
    r1 = _submit(ws, request_id=req)
    events_before = len(events.read_events(ws.events))
    r2 = _submit(ws, request_id=req)
    assert r2 == r1
    assert len(events.read_events(ws.events)) == events_before, "重放不写新事件"


def test_scan_ok_after_submit(tmp_path):
    from novelos.integrity import scan

    ws = _setup(tmp_path)
    _write_staging(ws, b"content\n")
    _submit(ws)
    report = scan(ws)
    assert report.chain_ok, report.chain_detail
    assert report.anchor_ok
