"""L0: 双层写前检查（冻结文档 06 §3 / §3.1）。

内部层损坏 → 拒绝且不写任何事件（exit 5 语义）；受管层带外 → 恰一个
OUT_OF_BAND_DETECTED 审计事件后拒绝（exit 2，信封 data = 扫描报告）；
derived_dirty（blocking: false）不阻断。
"""

import json

import pytest

from novelos import candidates, events, integrity, tasks, workspace
from novelos.protocol import EXIT_ENV, EXIT_ILLEGAL, OUT_OF_BAND_WRITE_DETECTED, WORKSPACE_CORRUPT
from novelos.transaction import OutOfBandError, WorkspaceCorruptError, guarded_transaction
from novelos.workspace import Workspace, read_yaml, write_yaml

pytestmark = pytest.mark.l0


def _init(tmp_path) -> Workspace:
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    return Workspace(tmp_path)


def _open_premise_task(ws: Workspace) -> dict:
    with guarded_transaction(ws) as tx:
        return tasks.open_task(
            ws,
            tx,
            task_type="premise",
            subject=None,
            brief="记忆当铺的想法",
            target_artifact_ref=None,
            request_id=None,
            session_id=None,
        )


def test_internal_corruption_refuses_without_writing_events(tmp_path):
    ws = _init(tmp_path)
    _open_premise_task(ws)
    staging = tmp_path / "work" / "task-001"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "premise.md").write_bytes(b"content\n")

    # 篡改末事件 → 内部层损坏
    raw = ws.events.read_bytes()
    lines = raw.decode("utf-8").splitlines()
    ev = json.loads(lines[-1])
    ev["type"] = "TAMPERED"
    lines[-1] = json.dumps(ev, ensure_ascii=False)
    tampered = ("\n".join(lines) + "\n").encode("utf-8")
    ws.events.write_bytes(tampered)

    with pytest.raises(WorkspaceCorruptError) as excinfo:
        with guarded_transaction(ws) as tx:
            candidates.submit_candidate(
                ws,
                tx,
                task_id="task-001",
                request_id=None,
                session_id=None,
                source_mode="REAL_AGENT",
            )
    assert excinfo.value.code == WORKSPACE_CORRUPT
    assert excinfo.value.exit_code == EXIT_ENV
    assert ws.events.read_bytes() == tampered, "损坏拒绝不得写任何事件"
    assert not (ws.tasks_dir / "task-001" / "candidates").exists()


def test_managed_out_of_band_writes_exactly_one_audit_event_then_refuses(tmp_path):
    ws = _init(tmp_path)
    with ws.managed_manifest.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("# 带外修改\n")
    lines_before = len(ws.events.read_bytes().splitlines())

    with pytest.raises(OutOfBandError) as excinfo:
        with guarded_transaction(ws) as tx:
            tasks.open_task(
                ws,
                tx,
                task_type="premise",
                subject=None,
                brief="想法",
                target_artifact_ref=None,
                request_id=None,
                session_id=None,
            )
    assert excinfo.value.code == OUT_OF_BAND_WRITE_DETECTED
    assert excinfo.value.exit_code == EXIT_ILLEGAL
    report_data = excinfo.value.report.to_data()
    assert [m["path"] for m in report_data["blocking_mismatches"]] == ["novelos.yaml"]

    new_events = events.read_events(ws.events)[lines_before:]
    assert len(new_events) == 1, "恰一个审计事件"
    audit = new_events[0]
    assert audit["type"] == "OUT_OF_BAND_DETECTED"
    assert audit["internal_manifest_hash"] is not None, "审计事件锚定 manifest"
    (change,) = audit["file_changes"]
    assert change["path"] == "novelos.yaml"
    assert change["before_hash"] != change["after_hash"]
    assert not (ws.tasks_dir / "task-001").exists(), "原任务操作未发生"

    # 审计事件自身链/锚定完好（受管失配仍在，属扫描器职责）
    report = integrity.scan(ws)
    assert report.chain_ok is True
    assert report.anchor_ok is True
    assert report.blocking_mismatches, "带外修改仍被扫描器报告"


def test_derived_dirty_does_not_block(tmp_path):
    ws = _init(tmp_path)
    # 将 novelos.yaml 账本条目改为非阻断（测试设置，直写允许）
    ledger = read_yaml(ws.ledger)
    ledger["entries"][0]["blocking"] = False
    write_yaml(ws.ledger, ledger)
    # 带外漂移 → 实算失配但 blocking: false → derived_dirty，不阻断
    with ws.managed_manifest.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("# 派生漂移\n")

    data = _open_premise_task(ws)
    assert data["task_id"] == "task-001"
    assert (ws.tasks_dir / "task-001").is_dir()

    report = integrity.scan(ws)
    assert report.blocking_mismatches == []
    assert [d["path"] for d in report.derived_dirty] == ["novelos.yaml"]
