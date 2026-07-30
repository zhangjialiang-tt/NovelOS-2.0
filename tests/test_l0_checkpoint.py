"""L0: checkpoint 最小进度快照（冻结文档 04 §3.7 / 06 §9 / 08 §6）。

前置状态（accepted premise artifact + DONE/REJECTED 两任务）经 WorkspaceTransaction
手工构造并 commit，不依赖兄弟领域模块（tasks/candidates/decisions 并行开发中）。
"""

import json

import pytest

from novelos import checkpoints, events, integrity, workspace
from novelos.protocol import (
    EXIT_ILLEGAL,
    NOT_INITIALIZED,
    NovelosError,
    combine_hash,
)
from novelos.transaction import WorkspaceTransaction
from novelos.workspace import Workspace, read_yaml

pytestmark = pytest.mark.l0

PREMISE_BYTES = "# 故事核心\n\n记忆当铺：人们典当记忆换钱。\n".encode("utf-8")


def _init(tmp_path) -> Workspace:
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    return Workspace(tmp_path)


def _task_json(task_id: str, status: str) -> bytes:
    return (
        json.dumps(
            {
                "task_id": task_id,
                "task_type": "premise",
                "status": status,
                "subject": "故事核心方向",
                "brief": "记忆当铺",
                "target_artifact_ref": None,
                "replacement": None,
                "inputs": [],
                "input_hashes": {},
                "current_candidate_revision": 1,
                "allowed_outputs": ["premise.md"],
                "validation_profile": "premise-v1",
                "capability_class": "CREATIVE_HIGH",
                "created_at": events.utc_now_iso(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _metrics_json(task_id: str) -> bytes:
    return (
        json.dumps(
            {
                "task_id": task_id,
                "context_files_read": 0,
                "retry_count": 0,
                "candidate_revisions": 1,
                "input_tokens": None,
                "output_tokens": None,
                "cached_tokens": None,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _build_premise_state(ws: Workspace, *, with_metrics: bool = True) -> str:
    """构造 accepted premise + 两任务前置状态；返回 story/premise.md 字节 hash。

    ledger 新增条目 last_event_id 指向本事务锚定的 COMMITTED 事件（其 file_changes
    携带 story/premise.md after_hash），使 integrity 受管层交叉核验通过。
    """
    commit_id = events.event_id_for(len(events.read_events(ws.events)))
    tx = WorkspaceTransaction(ws)
    managed_hash = tx.write("story/premise.md", PREMISE_BYTES)

    ledger = read_yaml(ws.ledger)
    entries = list(ledger["entries"])
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
                    "source_task": "task-001",
                    "source_candidate_revision": 1,
                    "decision_ref": {
                        "task_id": "task-001",
                        "candidate_revision": 1,
                        "decision": "ACCEPT",
                        "consumed": True,
                    },
                    "accepted_at": events.utc_now_iso(),
                }
            ],
        },
    )

    # task-001 DONE（staging 应被清理）；task-002 REJECTED（staging 保留审计）
    tx.write(".novelos/tasks/task-001/task.json", _task_json("task-001", "DONE"))
    tx.write("work/task-001/premise.md", b"staging one\n")
    if with_metrics:
        tx.write(".novelos/tasks/task-001/metrics.json", _metrics_json("task-001"))
    tx.write(".novelos/tasks/task-002/task.json", _task_json("task-002", "REJECTED"))
    tx.write("work/task-002/premise.md", b"staging two\n")

    tx.anchor_event(
        type="COMMITTED",
        transaction_id=events.new_transaction_id(),
        file_changes=[
            {"path": "story/premise.md", "before_hash": None, "after_hash": managed_hash}
        ],
        before_hash=None,
        after_hash=managed_hash,
        source_mode=None,
    )
    tx.commit()
    return managed_hash


def _run_checkpoint(ws: Workspace, *, label: str = "milestone", request_id: str | None = None) -> dict:
    tx = WorkspaceTransaction(ws)
    response = checkpoints.checkpoint(ws, tx, label=label, request_id=request_id, session_id=None)
    tx.commit()
    return response


# ---------------------------------------------------------------------------
# 形状 / hash / 锚定
# ---------------------------------------------------------------------------


def test_checkpoint_json_shape_accepted_refs_and_content_hash(tmp_path):
    ws = _init(tmp_path)
    _build_premise_state(ws)
    response = _run_checkpoint(ws, label="第一里程碑", request_id="req-cp-shape")

    assert response["checkpoint_id"] == "cp-001"
    assert response["accepted_artifact_refs"] == ["premise@1"]

    stored = json.loads((ws.checkpoints_dir / "cp-001.json").read_text(encoding="utf-8"))
    # 逐键形状（state_snapshot_hashes 恒空字典）
    assert set(stored.keys()) == {
        "checkpoint_id",
        "label",
        "accepted_refs",
        "state_snapshot_hashes",
        "content_hash",
        "created_at",
    }
    assert stored["checkpoint_id"] == "cp-001"
    assert stored["label"] == "第一里程碑"
    assert stored["accepted_refs"] == ["premise@1"]
    assert stored["state_snapshot_hashes"] == {}
    assert stored["created_at"].endswith("Z")

    # content_hash == combine_hash(ledger entries)（重算相等）
    ledger = read_yaml(ws.ledger)
    expected = combine_hash([(e["path"], e["hash"]) for e in ledger["entries"]])
    assert stored["content_hash"] == expected
    assert response["content_hash"] == expected


def test_checkpointed_event_anchored_and_manifest_covers(tmp_path):
    ws = _init(tmp_path)
    _build_premise_state(ws)
    response = _run_checkpoint(ws)

    last = events.read_events(ws.events)[-1]
    assert last["type"] == "CHECKPOINTED"
    assert last["after_hash"] == response["content_hash"]
    assert last["file_changes"] == []
    assert last["internal_manifest_hash"] is not None  # 末事件锚定 manifest

    manifest = read_yaml(ws.manifest)
    assert "checkpoints/cp-001.json" in manifest["files"]


# ---------------------------------------------------------------------------
# staging 清理
# ---------------------------------------------------------------------------


def test_staging_cleanup_done_removed_rejected_kept(tmp_path):
    ws = _init(tmp_path)
    _build_premise_state(ws)
    assert (ws.root / "work/task-001/premise.md").is_file()
    assert (ws.root / "work/task-002/premise.md").is_file()

    _run_checkpoint(ws)

    assert not (ws.root / "work/task-001").exists()  # DONE → 删
    assert (ws.root / "work/task-002/premise.md").is_file()  # REJECTED → 保留


# ---------------------------------------------------------------------------
# 延后项负向断言（run 生命周期 / ledger 清理均延后）
# ---------------------------------------------------------------------------


def test_deferred_items_no_runs_requests_not_shrunk(tmp_path):
    ws = _init(tmp_path)
    _build_premise_state(ws)
    requests_before = sorted(p.name for p in ws.requests_dir.glob("*.json"))

    _run_checkpoint(ws, request_id="req-cp-defer")

    # .novelos/runs/ 下无任何文件（骨架目录可存在但内容空）
    if ws.runs_dir.exists():
        assert not any(ws.runs_dir.rglob("*"))
    # requests/ 记录数 checkpoint 前后不减
    requests_after = sorted(p.name for p in ws.requests_dir.glob("*.json"))
    assert len(requests_after) >= len(requests_before)
    assert "req-cp-defer.json" in requests_after
    # checkpoint json 不含 run 相关键
    stored = json.loads((ws.checkpoints_dir / "cp-001.json").read_text(encoding="utf-8"))
    assert not any("run" in key for key in stored.keys())


# ---------------------------------------------------------------------------
# id 递增 / replay / 未初始化
# ---------------------------------------------------------------------------


def test_checkpoint_id_increments(tmp_path):
    ws = _init(tmp_path)
    _build_premise_state(ws)
    first = _run_checkpoint(ws)
    second = _run_checkpoint(ws)
    assert first["checkpoint_id"] == "cp-001"
    assert second["checkpoint_id"] == "cp-002"
    assert (ws.checkpoints_dir / "cp-002.json").is_file()


def test_replay_same_request_returns_original_no_new_events(tmp_path):
    ws = _init(tmp_path)
    _build_premise_state(ws)
    first = _run_checkpoint(ws, label="milestone", request_id="req-replay")
    count_after_first = len(events.read_events(ws.events))

    tx = WorkspaceTransaction(ws)
    second = checkpoints.checkpoint(
        ws, tx, label="milestone", request_id="req-replay", session_id=None
    )
    tx.commit()  # replay 命中：无缓冲写入、无事件

    assert second == first
    assert len(events.read_events(ws.events)) == count_after_first


def test_not_initialized_raises(tmp_path):
    ws = Workspace(tmp_path)
    tx = WorkspaceTransaction(ws)
    with pytest.raises(NovelosError) as excinfo:
        checkpoints.checkpoint(ws, tx, label="x", request_id=None, session_id=None)
    assert excinfo.value.code == NOT_INITIALIZED
    assert excinfo.value.exit_code == EXIT_ILLEGAL
    assert excinfo.value.hint


# ---------------------------------------------------------------------------
# integrity / metrics 联动
# ---------------------------------------------------------------------------


def test_integrity_scan_pass_after_checkpoint(tmp_path):
    ws = _init(tmp_path)
    _build_premise_state(ws)
    before = integrity.scan(ws)
    assert before.chain_ok and before.anchor_ok

    _run_checkpoint(ws)

    report = integrity.scan(ws)
    assert report.chain_ok
    assert report.anchor_ok
    assert not report.blocking_mismatches


def test_metrics_token_fields_untouched_by_checkpoint(tmp_path):
    ws = _init(tmp_path)
    _build_premise_state(ws)
    metrics_path = ws.tasks_dir / "task-001/metrics.json"
    before = json.loads(metrics_path.read_text(encoding="utf-8"))

    _run_checkpoint(ws)

    after = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert after == before  # checkpoint 不触碰任务度量
    assert after["input_tokens"] is None
    assert after["output_tokens"] is None
    assert after["cached_tokens"] is None
