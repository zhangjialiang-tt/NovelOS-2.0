"""L0: validate_task（premise-v1 结构检查、retry_count、旧 revision、审计事件）。

前置 task/候选状态经 WorkspaceTransaction 直接构造并 commit；候选经 candidates.submit_candidate
生成。冻结文档 04 §3.4、06 §4、07 §5。
"""

import json
from pathlib import Path

import pytest

from novelos import events, workspace
from novelos.candidates import submit_candidate, validate_task
from novelos.protocol import EXIT_ILLEGAL, ILLEGAL_OPERATION, NovelosError
from novelos.transaction import WorkspaceTransaction
from novelos.workspace import Workspace, read_yaml

pytestmark = pytest.mark.l0

TASK_ID = "task-001"
FIXTURES = Path(__file__).parent / "fixtures" / "premise"
VALID = (FIXTURES / "valid.md").read_bytes()
MISSING = (FIXTURES / "missing-section.md").read_bytes()


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


def _setup(tmp_path, *, task_id=TASK_ID):
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    ws = Workspace(tmp_path)
    task = {
        "task_id": task_id,
        "task_type": "premise",
        "status": "OPEN",
        "subject": "故事核心方向",
        "brief": "记忆当铺",
        "target_artifact_ref": None,
        "replacement": None,
        "inputs": [],
        "input_hashes": {},
        "current_candidate_revision": None,
        "allowed_outputs": ["premise.md"],
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


def _stage(ws, content: bytes, task_id=TASK_ID):
    staging = ws.root / "work" / task_id
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "premise.md").write_bytes(content)


def _submit(ws, task_id=TASK_ID):
    tx = WorkspaceTransaction(ws)
    result = submit_candidate(
        ws, tx, task_id=task_id, request_id=None, session_id=None, source_mode="REAL_AGENT"
    )
    tx.commit()
    return result


def _validate(ws, *, task_id=TASK_ID, revision=None, commit=True):
    tx = WorkspaceTransaction(ws)
    result = validate_task(ws, tx, task_id=task_id, revision=revision)
    if commit:
        tx.commit()
    return result


def _metrics(ws, task_id=TASK_ID):
    return json.loads((ws.tasks_dir / task_id / "metrics.json").read_text(encoding="utf-8"))


def _last_event(ws):
    return events.read_events(ws.events)[-1]


# ---------------------------------------------------------------------------


def test_valid_premise_passes_and_anchors(tmp_path):
    ws = _setup(tmp_path)
    _stage(ws, VALID)
    _submit(ws)
    result = _validate(ws)
    assert result["valid"] is True
    assert result["errors"] == []
    ev = _last_event(ws)
    assert ev["type"] == "VALIDATED"
    assert ev["internal_manifest_hash"] is not None, "VALIDATED 为锚定审计事件"
    assert ev["source_mode"] is None
    meta = read_yaml(ws.tasks_dir / TASK_ID / "candidates" / "rev-1" / "meta.yaml")
    assert meta["validation"]["valid"] is True


def test_missing_section_fails(tmp_path):
    ws = _setup(tmp_path)
    _stage(ws, MISSING)
    _submit(ws)
    result = _validate(ws)
    assert result["valid"] is False
    assert len(result["errors"]) == 1
    err = result["errors"][0]
    assert err["code"] == "VALIDATION_FAILED"
    assert "失败代价" in err["message"]
    assert "缺少小节" in err["message"]
    assert err["hint"]


def test_empty_section_fails(tmp_path):
    # 构造「失败代价」节正文纯空白。
    text = VALID.decode("utf-8").replace(
        "## 失败代价\n若查不清真相，他将永远缺失那段记忆，失去当铺继承权，并任由赎回者摆布身世。",
        "## 失败代价\n   \n",
    )
    assert "## 失败代价\n   \n" in text, "替换须生效"
    ws = _setup(tmp_path)
    _stage(ws, text.encode("utf-8"))
    _submit(ws)
    result = _validate(ws)
    assert result["valid"] is False
    messages = [e["message"] for e in result["errors"]]
    assert any("内容为空" in m and "失败代价" in m for m in messages)


def test_retry_count_only_on_failure(tmp_path):
    ws = _setup(tmp_path)
    _stage(ws, MISSING)
    _submit(ws)  # rev-1 缺节
    _validate(ws)
    assert _metrics(ws)["retry_count"] == 1
    _validate(ws)
    assert _metrics(ws)["retry_count"] == 2
    # 修复后成功校验不累加
    _stage(ws, VALID)
    _submit(ws)  # rev-2
    result = _validate(ws)
    assert result["valid"] is True
    assert _metrics(ws)["retry_count"] == 2


def test_old_revision_validatable(tmp_path):
    ws = _setup(tmp_path)
    _stage(ws, VALID)
    _submit(ws)  # rev-1
    _stage(ws, VALID)
    _submit(ws)  # rev-2，current=2
    task = json.loads((ws.tasks_dir / TASK_ID / "task.json").read_text(encoding="utf-8"))
    assert task["current_candidate_revision"] == 2
    result = _validate(ws, revision=1)  # 校验旧 revision（纯检查）
    assert result["valid"] is True


def test_no_candidate_illegal(tmp_path):
    ws = _setup(tmp_path)  # current_candidate_revision None，无候选目录
    with pytest.raises(NovelosError) as excinfo:
        _validate(ws)
    assert excinfo.value.code == ILLEGAL_OPERATION
    assert excinfo.value.exit_code == EXIT_ILLEGAL


def test_task_not_found(tmp_path):
    ws = _setup(tmp_path)
    with pytest.raises(NovelosError) as excinfo:
        _validate(ws, task_id="task-999")
    assert excinfo.value.code == "TASK_NOT_FOUND"


def test_scan_ok_after_validate(tmp_path):
    from novelos.integrity import scan

    ws = _setup(tmp_path)
    _stage(ws, VALID)
    _submit(ws)
    _validate(ws)
    report = scan(ws)
    assert report.chain_ok, report.chain_detail
    assert report.anchor_ok
