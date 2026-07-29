"""L0: workspace layout, YAML I/O, init semantics."""

import pytest

from novelos import workspace
from novelos.protocol import EXIT_ENV, EXIT_ILLEGAL, ILLEGAL_OPERATION, WORKSPACE_CORRUPT, NovelosError
from novelos.workspace import SKELETON_DIRS, Workspace, read_yaml

pytestmark = pytest.mark.l0


def test_init_creates_exact_skeleton(tmp_path):
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)

    for rel in SKELETON_DIRS:
        assert (tmp_path / rel).is_dir(), rel

    assert (tmp_path / "novelos.yaml").is_file()
    assert (tmp_path / ".novelos" / "hash-ledger.yaml").is_file()
    assert (tmp_path / ".novelos" / "internal-manifest.yaml").is_file()
    assert (tmp_path / ".novelos" / "events.jsonl").is_file()
    assert (tmp_path / ".novelos" / "decisions.jsonl").is_file()


def test_all_written_files_are_lf_only(tmp_path):
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    files = [
        tmp_path / "novelos.yaml",
        tmp_path / ".novelos" / "hash-ledger.yaml",
        tmp_path / ".novelos" / "internal-manifest.yaml",
        tmp_path / ".novelos" / "events.jsonl",
        tmp_path / ".novelos" / "decisions.jsonl",
    ]
    for f in files:
        assert b"\r\n" not in f.read_bytes(), f.name


def test_ledger_entry_shape(tmp_path):
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    ledger = read_yaml(tmp_path / ".novelos" / "hash-ledger.yaml")
    (entry,) = ledger["entries"]
    assert set(entry) == {"path", "hash", "last_event_id", "last_artifact_revision", "blocking"}
    assert entry["path"] == "novelos.yaml"
    assert entry["hash"].startswith("sha256:")
    assert entry["last_event_id"] == "ev-000001"
    assert entry["last_artifact_revision"] is None
    assert entry["blocking"] is True


def test_reinit_raises_illegal_operation(tmp_path):
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    with pytest.raises(NovelosError) as excinfo:
        workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    assert excinfo.value.code == ILLEGAL_OPERATION
    assert excinfo.value.exit_code == EXIT_ILLEGAL


def test_partial_internal_dir_is_corrupt(tmp_path):
    (tmp_path / ".novelos").mkdir()
    with pytest.raises(NovelosError) as excinfo:
        workspace.open(tmp_path, require_initialized=False)
    assert excinfo.value.code == WORKSPACE_CORRUPT
    assert excinfo.value.exit_code == EXIT_ENV
    # init also refuses the partial state as corrupt
    with pytest.raises(NovelosError) as excinfo2:
        workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    assert excinfo2.value.code == WORKSPACE_CORRUPT


def test_foreign_files_survive_init(tmp_path):
    foreign = tmp_path / "notes.txt"
    foreign.write_text("user data", encoding="utf-8")
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    assert foreign.read_text(encoding="utf-8") == "user data"


def test_project_name_defaults_to_dir_basename(tmp_path):
    workspace.init(tmp_path, None, request_id=None, session_id=None)
    manifest = read_yaml(tmp_path / "novelos.yaml")
    assert manifest["project_name"] == tmp_path.resolve().name
    assert manifest["protocol_version"] == "1.0"


def test_open_require_initialized(tmp_path):
    ws = workspace.open(tmp_path, require_initialized=False)
    assert isinstance(ws, Workspace)
    assert ws.is_initialized() is False
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    ws2 = workspace.open(tmp_path, require_initialized=True)
    assert ws2.is_initialized() is True
