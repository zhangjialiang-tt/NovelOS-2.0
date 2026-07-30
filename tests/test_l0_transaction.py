"""L0: 工作区锁 + 进程内原子事务（回滚字节一致、回滚失败升级损坏）。

四注入点（after:story/premise.md / after:.novelos/artifacts/premise/meta.yaml /
after:.novelos/decisions.jsonl / after:.novelos/internal-manifest.yaml）场景
依赖 decide ACCEPT 全链，见本文件末（C5 落地后启用）。
"""

import json
import logging
import os
import subprocess
import sys

import pytest

from novelos import events, workspace
from novelos.protocol import EXIT_ILLEGAL, ILLEGAL_OPERATION, NovelosError
from novelos.transaction import (
    WorkspaceCorruptError,
    WorkspaceLock,
    WorkspaceTransaction,
    guarded_transaction,
)
from novelos.workspace import Workspace, read_yaml

pytestmark = pytest.mark.l0


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _snapshot(root) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = path.read_bytes()
    return out


# ---------------------------------------------------------------------------
# 锁
# ---------------------------------------------------------------------------


def test_lock_acquire_creates_and_release_removes(tmp_path):
    ws = Workspace(tmp_path)
    lock = WorkspaceLock(ws)
    lock.acquire()
    assert lock.lock_path.is_file()
    holder = json.loads(lock.lock_path.read_text(encoding="utf-8"))
    assert holder["pid"] == os.getpid()
    assert len(holder["owner_token"]) == 32
    lock.release()
    assert not lock.lock_path.exists()


def test_lock_second_acquire_while_held_is_illegal(tmp_path):
    ws = Workspace(tmp_path)
    first = WorkspaceLock(ws)
    first.acquire()
    try:
        second = WorkspaceLock(ws)
        with pytest.raises(NovelosError) as excinfo:
            second.acquire()
        assert excinfo.value.code == ILLEGAL_OPERATION
        assert excinfo.value.exit_code == EXIT_ILLEGAL
        assert "占用" in excinfo.value.message or "使用" in excinfo.value.message
    finally:
        first.release()


def test_release_only_removes_own_token(tmp_path):
    ws = Workspace(tmp_path)
    # 伪造他人锁（不同 owner_token）
    foreign = json.dumps({"pid": os.getpid(), "owner_token": "f" * 32, "acquired_at": "t"})
    (tmp_path / ".novelos.lock").write_text(foreign + "\n", encoding="utf-8")
    lock = WorkspaceLock(ws)
    lock._token = "e" * 32  # 本进程自认的 token
    lock.release()
    assert (tmp_path / ".novelos.lock").is_file(), "不得删除非己锁"
    assert json.loads((tmp_path / ".novelos.lock").read_text(encoding="utf-8"))["owner_token"] == "f" * 32


def test_stale_dead_pid_is_taken_over(tmp_path):
    ws = Workspace(tmp_path)
    stale = json.dumps({"pid": _dead_pid(), "owner_token": "d" * 32, "acquired_at": "t"})
    (tmp_path / ".novelos.lock").write_text(stale + "\n", encoding="utf-8")
    lock = WorkspaceLock(ws)
    lock.acquire()
    try:
        holder = json.loads(lock.lock_path.read_text(encoding="utf-8"))
        assert holder["pid"] == os.getpid()
        assert holder["owner_token"] != "d" * 32
    finally:
        lock.release()
    assert not (tmp_path / ".novelos.lock").exists()


def test_unprovable_death_is_treated_alive(tmp_path, monkeypatch):
    """EPERM/其他错误语义：探测不得证死 → 不接管（monkeypatch 存活探测恒真）。"""
    from novelos import transaction as tx_mod

    monkeypatch.setattr(tx_mod, "_process_alive", lambda pid: True)
    ws = Workspace(tmp_path)
    stale = json.dumps({"pid": _dead_pid(), "owner_token": "d" * 32, "acquired_at": "t"})
    (tmp_path / ".novelos.lock").write_text(stale + "\n", encoding="utf-8")
    lock = WorkspaceLock(ws)
    with pytest.raises(NovelosError) as excinfo:
        lock.acquire()
    assert excinfo.value.code == ILLEGAL_OPERATION
    assert (tmp_path / ".novelos.lock").is_file(), "未接管则原锁保留"
    (tmp_path / ".novelos.lock").unlink()


# ---------------------------------------------------------------------------
# 事务：字节一致回滚 + 升级损坏
# ---------------------------------------------------------------------------


def _init_ws(tmp_path) -> Workspace:
    workspace.init(tmp_path, "demo", request_id=None, session_id=None)
    return Workspace(tmp_path)


def test_commit_applies_buffers_and_anchors(tmp_path):
    ws = _init_ws(tmp_path)
    tx = WorkspaceTransaction(ws)
    content_hash = tx.write("story/premise.md", "核心\n".encode("utf-8"))
    tx.write_yaml(".novelos/tasks/task-001/meta.yaml", {"status": "OPEN"})
    tx.anchor_event(
        type="TEST_ANCHOR",
        transaction_id=events.new_transaction_id(),
        file_changes=[{"path": "story/premise.md", "before_hash": None, "after_hash": content_hash}],
        before_hash=None,
        after_hash=content_hash,
        source_mode=None,
    )
    tx.commit()

    assert (tmp_path / "story" / "premise.md").read_bytes() == "核心\n".encode("utf-8")
    assert read_yaml(tmp_path / ".novelos/tasks/task-001/meta.yaml") == {"status": "OPEN"}
    manifest = read_yaml(ws.manifest)["files"]
    assert "tasks/task-001/meta.yaml" in manifest
    assert "decisions.jsonl" not in manifest
    last = events.read_events(ws.events)[-1]
    assert last["type"] == "TEST_ANCHOR"
    assert last["internal_manifest_hash"] is not None


def test_inject_after_managed_file_rolls_back_byte_identical(tmp_path):
    ws = _init_ws(tmp_path)
    before = _snapshot(tmp_path)
    events_len = len(ws.events.read_bytes().splitlines())

    tx = WorkspaceTransaction(ws)

    def boom(stage: str) -> None:
        if stage == "after:story/premise.md":
            raise RuntimeError("injected apply failure")

    tx.inject = boom
    tx.write("story/premise.md", b"partial")
    tx.write_yaml(".novelos/extra.yaml", {"x": 1})
    tx.anchor_event(
        type="NEVER_LANDS",
        transaction_id=events.new_transaction_id(),
        file_changes=[],
        source_mode=None,
    )
    with pytest.raises(RuntimeError, match="injected apply failure"):
        tx.commit()

    assert _snapshot(tmp_path) == before, "回滚后逐文件字节一致"
    assert len(ws.events.read_bytes().splitlines()) == events_len, "events 无新增"


def test_rollback_failure_escalates_to_corrupt(tmp_path, caplog):
    ws = _init_ws(tmp_path)
    before = _snapshot(tmp_path)

    tx = WorkspaceTransaction(ws)
    tx.inject = lambda stage: (_ for _ in ()).throw(RuntimeError("apply fail")) if stage == "after:novelos.yaml" else None
    tx.inject_rollback_fail = True
    tx.write("novelos.yaml", b"corrupting bytes")
    with caplog.at_level(logging.ERROR, logger="novelos"):
        with pytest.raises(WorkspaceCorruptError) as excinfo:
            tx.commit()
    assert excinfo.value.code == "WORKSPACE_CORRUPT"
    assert excinfo.value.exit_code == 5
    messages = " | ".join(r.getMessage() for r in caplog.records)
    assert "apply fail" in messages, "stderr 日志含原始异常"
    assert "rollback failure injected" in messages, "stderr 日志含回滚异常"
    # 回滚失败 → 工作区可能撕裂（此处 novelos.yaml 已被覆写且未恢复）
    assert (tmp_path / "novelos.yaml").read_bytes() == b"corrupting bytes"
    assert _snapshot(tmp_path) != before


def test_delete_dir_buffers_and_rollback_restores(tmp_path):
    ws = _init_ws(tmp_path)
    staging = tmp_path / "work" / "task-001"
    staging.mkdir(parents=True)
    (staging / "premise.md").write_bytes(b"content")
    (staging / "sub").mkdir()
    (staging / "sub" / "note.txt").write_bytes(b"note")
    before = _snapshot(tmp_path)

    tx = WorkspaceTransaction(ws)
    tx.delete_dir("work/task-001")
    tx.anchor_event(
        type="CLEANUP", transaction_id=events.new_transaction_id(), file_changes=[], source_mode=None
    )
    tx.commit()
    assert not staging.exists()

    # 再开一个会失败的事务删除 → 回滚恢复原文件
    staging.mkdir(parents=True)
    (staging / "premise.md").write_bytes(b"content2")
    snap2 = _snapshot(tmp_path)
    tx2 = WorkspaceTransaction(ws)
    tx2.inject = lambda stage: (_ for _ in ()).throw(RuntimeError("fail")) if stage.startswith("after:") else None
    tx2.delete_dir("work/task-001")
    tx2.anchor_event(
        type="NEVER", transaction_id=events.new_transaction_id(), file_changes=[], source_mode=None
    )
    with pytest.raises(RuntimeError):
        tx2.commit()
    after = _snapshot(tmp_path)
    # manifest/anchor 未变（事件回滚），work 文件恢复
    assert after.get("work/task-001/premise.md") == b"content2"
    assert after == snap2


def test_events_jsonl_write_rejected(tmp_path):
    ws = _init_ws(tmp_path)
    tx = WorkspaceTransaction(ws)
    with pytest.raises(ValueError):
        tx.write(".novelos/events.jsonl", b"x")
    with pytest.raises(ValueError):
        tx.delete_file(".novelos/events.jsonl")
    with pytest.raises(ValueError):
        tx.write("../escape.md", b"x")
    with pytest.raises(ValueError):
        tx.write("a/../b.md", b"x")


def test_guarded_transaction_commits_on_success_and_lock_released(tmp_path):
    ws = _init_ws(tmp_path)
    with guarded_transaction(ws) as tx:
        tx.write("state/scratch.txt", b"s")
        tx.anchor_event(
            type="SCRATCH",
            transaction_id=events.new_transaction_id(),
            file_changes=[],
            source_mode=None,
        )
    assert (tmp_path / "state" / "scratch.txt").read_bytes() == b"s"
    assert not (tmp_path / ".novelos.lock").exists(), "commit 后锁释放"
