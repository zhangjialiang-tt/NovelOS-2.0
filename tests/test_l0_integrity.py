"""L0: two-layer integrity scanner."""

import pytest

from novelos import integrity, workspace
from novelos.workspace import Workspace, read_yaml, write_yaml

pytestmark = pytest.mark.l0


def _scan(tmp_path):
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    return Workspace(tmp_path), integrity.scan(Workspace(tmp_path))


def test_fresh_workspace_clean(tmp_path):
    _, report = _scan(tmp_path)
    assert report.scanned_files == 1
    assert report.blocking_mismatches == []
    assert report.derived_dirty == []
    assert report.chain_ok is True
    assert report.anchor_ok is True


def test_tampered_novelos_yaml_is_blocking(tmp_path):
    ws, _ = _scan(tmp_path)
    ledger = read_yaml(ws.ledger)
    expected = ledger["entries"][0]["hash"]
    with ws.managed_manifest.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("# tampered\n")

    report = integrity.scan(ws)
    assert len(report.blocking_mismatches) == 1
    entry = report.blocking_mismatches[0]
    assert entry["path"] == "novelos.yaml"
    assert entry["expected_hash"] == expected
    assert entry["actual_hash"] != expected
    assert entry["last_legitimate_event"] == "ev-000001"
    assert report.derived_dirty == []


def test_broken_chain_detected(tmp_path):
    ws, _ = _scan(tmp_path)
    ws.events.write_bytes(b'{"event_id": "ev-999999"}\n')
    report = integrity.scan(ws)
    assert report.chain_ok is False


def test_truncated_manifest_breaks_anchor(tmp_path):
    ws, _ = _scan(tmp_path)
    ws.manifest.write_bytes(b"")
    report = integrity.scan(ws)
    assert report.anchor_ok is False


def test_ledger_event_divergence_breaks_chain(tmp_path):
    ws, _ = _scan(tmp_path)
    ledger = read_yaml(ws.ledger)
    ledger["entries"][0]["hash"] = "sha256:" + "f" * 64
    write_yaml(ws.ledger, ledger)
    report = integrity.scan(ws)
    assert report.chain_ok is False


def test_report_to_data_shape(tmp_path):
    _, report = _scan(tmp_path)
    data = report.to_data()
    assert set(data) == {
        "scanned_files",
        "blocking_mismatches",
        "derived_dirty",
        "chain_ok",
        "anchor_ok",
        "chain_detail",
    }
