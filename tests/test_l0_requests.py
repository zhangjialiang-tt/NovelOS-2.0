"""L0: request ledger idempotency (冻结文档 04 §1.5 / 06 §8)."""

import json

import pytest

from novelos import workspace
from novelos.protocol import EXIT_ILLEGAL, REQUEST_ID_CONFLICT, NovelosError
from novelos.workspace import Workspace

pytestmark = pytest.mark.l0

REQUEST_ID = "11111111-2222-3333-4444-555555555555"


def test_init_with_request_id_writes_ledger(tmp_path):
    workspace.init(tmp_path, "demo", request_id=REQUEST_ID, session_id=None)
    record_path = Workspace(tmp_path).requests_dir / f"{REQUEST_ID}.json"
    assert record_path.is_file()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["request_id"] == REQUEST_ID
    assert record["command"] == "init"
    assert record["arguments_hash"].startswith("sha256:")
    assert record["response"] == {"initialized": True, "workspace_root": str(tmp_path.resolve())}


def test_replay_returns_stored_response_without_new_events(tmp_path):
    first = workspace.init(tmp_path, "demo", request_id=REQUEST_ID, session_id=None)
    events_path = Workspace(tmp_path).events
    assert len(events_path.read_bytes().splitlines()) == 1

    second = workspace.init(tmp_path, "demo", request_id=REQUEST_ID, session_id=None)
    assert second == first
    assert len(events_path.read_bytes().splitlines()) == 1


def test_same_id_different_args_conflict(tmp_path):
    workspace.init(tmp_path, "demo", request_id=REQUEST_ID, session_id=None)
    with pytest.raises(NovelosError) as excinfo:
        workspace.init(tmp_path, "other-name", request_id=REQUEST_ID, session_id=None)
    assert excinfo.value.code == REQUEST_ID_CONFLICT
    assert excinfo.value.exit_code == EXIT_ILLEGAL


def test_request_ledger_covered_by_manifest(tmp_path):
    workspace.init(tmp_path, "demo", request_id=REQUEST_ID, session_id=None)
    from novelos.workspace import read_yaml

    manifest = read_yaml(Workspace(tmp_path).manifest)
    assert f"requests/{REQUEST_ID}.json" in manifest["files"]
    # 06 §3.1 三分：decisions.jsonl 经事件绑定，不在 manifest
    assert "decisions.jsonl" not in manifest["files"]
