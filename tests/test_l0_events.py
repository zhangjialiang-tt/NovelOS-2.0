"""L0: event chain + r5 anchoring invariant."""

import pytest

from novelos import workspace
from novelos.events import (
    GENESIS_PREV_HASH,
    compute_event_hash,
    event_id_for,
    read_events,
    verify_chain,
)
from novelos.protocol import hash_file
from novelos.workspace import Workspace

pytestmark = pytest.mark.l0


def _init(tmp_path) -> Workspace:
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    return Workspace(tmp_path)


def test_genesis_prev_hash(tmp_path):
    ws = _init(tmp_path)
    (event,) = read_events(ws.events)
    assert event["prev_event_hash"] == GENESIS_PREV_HASH == "0" * 64


def test_event_id_sequence_starts_at_one(tmp_path):
    ws = _init(tmp_path)
    (event,) = read_events(ws.events)
    assert event["event_id"] == "ev-000001"
    assert event_id_for(0) == "ev-000001"
    assert event_id_for(11) == "ev-000012"


def test_event_hash_recomputation_matches(tmp_path):
    ws = _init(tmp_path)
    (event,) = read_events(ws.events)
    assert compute_event_hash(event) == event["event_hash"]


def test_initialized_event_anchors_manifest(tmp_path):
    """r5 锚定不变量：INITIALIZED 末事件锚定 internal-manifest.yaml 字节 hash。"""
    ws = _init(tmp_path)
    (event,) = read_events(ws.events)
    assert event["type"] == "INITIALIZED"
    assert event["internal_manifest_hash"] is not None
    assert event["internal_manifest_hash"] == hash_file(ws.manifest)
    assert event["writer"] == "NOVEL_OS_CORE"
    assert event["source_mode"] is None


def test_verify_chain_ok_on_fresh_workspace(tmp_path):
    ws = _init(tmp_path)
    ok, detail = verify_chain(ws.events)
    assert ok, detail


def test_verify_chain_fails_after_byte_flip(tmp_path):
    ws = _init(tmp_path)
    raw = ws.events.read_bytes()
    mid = len(raw) // 2
    flipped = bytes([raw[mid] ^ 0x01])
    ws.events.write_bytes(raw[:mid] + flipped + raw[mid + 1:])
    ok, _ = verify_chain(ws.events)
    assert ok is False


def test_event_file_changes_record_novelos_yaml(tmp_path):
    ws = _init(tmp_path)
    (event,) = read_events(ws.events)
    (change,) = event["file_changes"]
    assert change["path"] == "novelos.yaml"
    assert change["before_hash"] is None
    assert change["after_hash"] == hash_file(ws.managed_manifest)
    assert event["after_hash"] == change["after_hash"]
