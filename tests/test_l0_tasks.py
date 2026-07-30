"""L0: tasks 域 open-or-resume 与任务工作包（冻结文档 07 §2/§3/§6）。"""

import json

import pytest

from novelos import events, integrity, tasks, workspace
from novelos.protocol import (
    EXIT_ILLEGAL,
    EXIT_USAGE,
    ILLEGAL_OPERATION,
    REQUEST_ID_CONFLICT,
    USAGE_ERROR,
    NovelosError,
)
from novelos.transaction import WorkspaceTransaction, guarded_transaction
from novelos.workspace import read_yaml

pytestmark = pytest.mark.l0

_BRIEF = "记忆当铺：人们典当记忆换钱，主角是当铺学徒"


def _init_ws(tmp_path):
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    return workspace.open(tmp_path, require_initialized=True)


def _open(ws, **kw):
    """经 guarded_transaction 调用 open_task（提交由上下文管理器负责）。"""
    defaults = dict(
        task_type="premise",
        subject=None,
        brief=_BRIEF,
        target_artifact_ref=None,
        request_id=None,
        session_id=None,
    )
    defaults.update(kw)
    with guarded_transaction(ws) as tx:
        return tasks.open_task(ws, tx, **defaults)


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _set_task_status(ws, task_id, status):
    """前置态：经 WorkspaceTransaction 直接改 task.json 状态并 commit。"""
    path = ws.tasks_dir / task_id / "task.json"
    data = _read_json(path)
    data["status"] = status
    tx = WorkspaceTransaction(ws)
    tx.write(
        f".novelos/tasks/{task_id}/task.json",
        (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    tx.commit()


def _write_revision_notes(ws, task_id, rounds):
    """前置态：经 WorkspaceTransaction 写逐轮 revision-notes 并 commit。"""
    tx = WorkspaceTransaction(ws)
    for k in rounds:
        rel = f".novelos/tasks/{task_id}/context/revision-notes/rev-{k:03d}.md"
        tx.write(rel, f"# 作者修改意见（第 {k} 轮）\n\n把失败代价写具体\n".encode("utf-8"))
    tx.commit()


def _mark_premise_accepted(ws):
    """前置态：经 WorkspaceTransaction 写 artifacts/premise/meta.yaml accepted 并 commit。"""
    tx = WorkspaceTransaction(ws)
    tx.write_yaml(
        ".novelos/artifacts/premise/meta.yaml",
        {"artifact_id": "premise", "artifact_type": "PREMISE", "managed_path": "story/premise.md", "accepted": 1},
    )
    tx.commit()


def _assert_error(excinfo, code, exit_code):
    err = excinfo.value
    assert err.code == code
    assert err.exit_code == exit_code
    assert err.hint  # hint 非空


def test_open_task_creates_full_package(tmp_path):
    ws = _init_ws(tmp_path)
    result = _open(ws, subject="故事核心方向")

    assert result["task_id"] == "task-001"
    assert result["package_path"] == ".novelos/tasks/task-001"
    assert result["staging_path"] == "work/task-001"
    assert result["instructions_ref"] == ".novelos/tasks/task-001/instructions.md"
    assert result["resumed"] is False
    assert result["original_brief"] == _BRIEF
    assert result["revision_guidance_ref"] is None

    # task.json 字段集全断言（契约逐字段）
    task = _read_json(ws.tasks_dir / "task-001" / "task.json")
    assert set(task) == {
        "task_id",
        "task_type",
        "status",
        "subject",
        "brief",
        "target_artifact_ref",
        "replacement",
        "inputs",
        "input_hashes",
        "current_candidate_revision",
        "allowed_outputs",
        "validation_profile",
        "capability_class",
        "created_at",
    }
    assert task["task_id"] == "task-001"
    assert task["task_type"] == "premise"
    assert task["status"] == "OPEN"
    assert task["subject"] == "故事核心方向"
    assert task["brief"] == _BRIEF
    assert task["target_artifact_ref"] is None
    assert task["replacement"] is None
    assert task["inputs"] == []
    assert task["input_hashes"] == {}
    assert task["current_candidate_revision"] is None
    assert task["allowed_outputs"] == ["premise.md"]
    assert task["validation_profile"] == "premise-v1"
    assert task["capability_class"] == "CREATIVE_HIGH"
    assert task["created_at"].endswith("Z")

    # instructions 六要素关键词
    instructions = (ws.tasks_dir / "task-001" / "instructions.md").read_text(encoding="utf-8")
    assert "确定故事核心方向" in instructions and "story/premise.md" in instructions  # ① 目的
    assert "context/" in instructions and "revision-notes" in instructions  # ② 输入
    assert "premise.md" in instructions and "一句话故事钩子" in instructions  # ③ output contract
    assert "缺少小节" in instructions  # ④ validate
    assert "work/task-001/" in instructions and "SKILL.md" in instructions  # ⑤ 硬规则
    assert "present" in instructions and "decide" in instructions  # ⑥ 作者确认
    # 八节标题逐字
    for section in (
        "一句话故事钩子",
        "主角是谁",
        "主角主动目标",
        "核心阻力",
        "失败代价",
        "主要读者期待",
        "结局方向",
        "尚待作者决定的问题",
    ):
        assert section in instructions

    # context-index 空 entries
    ctx_index = _read_json(ws.tasks_dir / "task-001" / "context-index.json")
    assert ctx_index == {"task_id": "task-001", "entries": []}

    # metrics 初值（token None）
    metrics = _read_json(ws.tasks_dir / "task-001" / "metrics.json")
    assert metrics == {
        "task_id": "task-001",
        "context_files_read": 0,
        "retry_count": 0,
        "candidate_revisions": 0,
        "input_tokens": None,
        "output_tokens": None,
        "cached_tokens": None,
    }

    # staging 与 context 目录存在
    assert (tmp_path / "work" / "task-001").is_dir()
    assert (ws.tasks_dir / "task-001" / "context").is_dir()


def test_task_id_sequence_after_rejected(tmp_path):
    ws = _init_ws(tmp_path)
    first = _open(ws)
    assert first["task_id"] == "task-001"

    _set_task_status(ws, "task-001", "REJECTED")

    second = _open(ws)
    assert second["task_id"] == "task-002"
    assert second["resumed"] is False


def test_resume_active_task(tmp_path):
    ws = _init_ws(tmp_path)
    created = _open(ws, brief="原始想法 A", request_id="req-a")
    assert created["task_id"] == "task-001"

    events_before = len(events.read_events(ws.events))
    requests_before = sorted(p.name for p in ws.requests_dir.glob("*.json"))

    # active 任务再 open（不带 brief）→ resume
    resumed = _open(ws, brief=None, request_id="req-b")
    assert resumed["task_id"] == "task-001"
    assert resumed["resumed"] is True
    assert resumed["original_brief"] == "原始想法 A"
    assert resumed["package_path"] == ".novelos/tasks/task-001"
    assert resumed["staging_path"] == "work/task-001"

    # 无新事件、无新 request 记录
    assert len(events.read_events(ws.events)) == events_before
    assert sorted(p.name for p in ws.requests_dir.glob("*.json")) == requests_before
    assert not (ws.requests_dir / "req-b.json").exists()


def test_revision_guidance_ref(tmp_path):
    ws = _init_ws(tmp_path)
    created = _open(ws)
    assert created["revision_guidance_ref"] is None  # 无 revision-notes

    _write_revision_notes(ws, "task-001", (1, 2))

    resumed = _open(ws, brief=None)
    assert resumed["resumed"] is True
    assert resumed["revision_guidance_ref"] == ".novelos/tasks/task-001/context/revision-notes/rev-002.md"
    assert (tmp_path / resumed["revision_guidance_ref"]).is_file()


def test_premise_accepted_blocks_open(tmp_path):
    ws = _init_ws(tmp_path)
    _mark_premise_accepted(ws)

    with pytest.raises(NovelosError) as excinfo:
        _open(ws)
    _assert_error(excinfo, ILLEGAL_OPERATION, EXIT_ILLEGAL)


def test_unsupported_task_type(tmp_path):
    ws = _init_ws(tmp_path)
    with pytest.raises(NovelosError) as excinfo:
        _open(ws, task_type="chapter")
    _assert_error(excinfo, USAGE_ERROR, EXIT_USAGE)


def test_blank_brief_rejected(tmp_path):
    ws = _init_ws(tmp_path)
    with pytest.raises(NovelosError) as excinfo:
        _open(ws, brief="   ")
    _assert_error(excinfo, USAGE_ERROR, EXIT_USAGE)


def test_target_artifact_ref_rejected_even_with_active(tmp_path):
    ws = _init_ws(tmp_path)
    _open(ws)  # active task 存在
    with pytest.raises(NovelosError) as excinfo:
        _open(ws, target_artifact_ref="premise@1")
    # 检查序：task_type 后、resume 前 → 即使有 active 任务亦拒绝
    _assert_error(excinfo, USAGE_ERROR, EXIT_USAGE)


def test_replay_and_conflict(tmp_path):
    ws = _init_ws(tmp_path)
    first = _open(ws, brief="想法 X", request_id="req-1")
    assert first["task_id"] == "task-001"
    events_after_create = len(events.read_events(ws.events))

    # 同 request_id + 同参数 → 返回原响应，无新事件
    again = _open(ws, brief="想法 X", request_id="req-1")
    assert again == first
    assert len(events.read_events(ws.events)) == events_after_create

    # 同 request_id 异参 → REQUEST_ID_CONFLICT
    with pytest.raises(NovelosError) as excinfo:
        _open(ws, brief="想法 Y", request_id="req-1")
    _assert_error(excinfo, REQUEST_ID_CONFLICT, EXIT_ILLEGAL)


def test_open_then_scan_pass(tmp_path):
    ws = _init_ws(tmp_path)
    _open(ws)

    report = integrity.scan(ws)
    assert report.chain_ok
    assert report.anchor_ok

    task_opened = [e for e in events.read_events(ws.events) if e["type"] == "TASK_OPENED"]
    assert len(task_opened) == 1
    assert task_opened[0]["task_id"] == "task-001"
    assert task_opened[0]["internal_manifest_hash"]  # 锚定事件携带 manifest hash
