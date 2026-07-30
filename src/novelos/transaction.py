"""NovelOS 进程内原子事务 + 统一根目录工作区锁 + 双层写前检查。

冻结依据：06 §3（写前扫描双层）、06 §3.1（内部层损坏拒绝 / 三分）、06 §6（事件锚定 r5）、
02 §7.5（原子切换场景）。评审定案：in_process_atomicity required、concurrent_command_lock required、
crash_reconciliation deferred（journal reconcile 与 OS 级文件锁属 Goal 5）。

应用序（commit）：①其他内部文件 → ②受管作品文件 → ③decisions.jsonl → ④hash-ledger.yaml
→ ⑤internal-manifest.yaml → ⑥events.jsonl 单次追加。回滚成功 → 重抛原异常；
回滚失败 → 升级 WorkspaceCorruptError（双异常经 logging 写 stderr）。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from novelos import events
from novelos.events import utc_now_iso
from novelos.integrity import ScanReport, scan_internal, scan_managed
from novelos.protocol import (
    EXIT_ENV,
    EXIT_ILLEGAL,
    ILLEGAL_OPERATION,
    OUT_OF_BAND_WRITE_DETECTED,
    WORKSPACE_CORRUPT,
    ErrorItem,
    NovelosError,
    canonical_json,
    hash_file,
    sha256_hex,
)

if TYPE_CHECKING:
    from novelos.workspace import Workspace

log = logging.getLogger("novelos")

# manifest 三分排除项（06 §3.1）：events 链自证、decisions 经事件绑定、manifest 自身不可自涵。
_MANIFEST_EXCLUDE = (
    ".novelos/events.jsonl",
    ".novelos/decisions.jsonl",
    ".novelos/internal-manifest.yaml",
)


def _read_yaml(path: Path) -> object:
    # 延迟导入 workspace 会在 import 期成环（integrity → workspace → transaction）；
    # read_yaml 语义单点复用于此。
    from novelos.workspace import read_yaml

    return read_yaml(path)


def _process_alive(pid: int) -> bool:
    """探测进程是否存活。POSIX 用 os.kill(pid, 0)（ESRCH = 死）；
    Windows 的 os.kill 对已退出进程不可靠（Python 3.13/win 不抛错），
    改用 OpenProcess + GetExitCodeProcess（STILL_ACTIVE = 259 判定）。"""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False  # 无法打开（不存在/无权限）→ 按死进程处理（仅可证伪存活）
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True  # 查询失败 → 保守视为存活，不接管
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:  # ESRCH → 死进程
        return False
    except (PermissionError, OSError):  # EPERM 等 → 可能存活 → 不接管
        return True
    return True


class WorkspaceLock:
    """统一根目录锁 <workspace>/.novelos.lock。

    init 前 .novelos/ 尚不存在，故锁不落 .novelos/ 内；锁不在 managed ledger、
    不在 internal-manifest、integrity 扫描不覆盖（路径不属受管/内部集合）。
    v1 已知限：PID 复用窗口——owner_token 使 release 只删自己的锁；仅可证死的
    进程（ESRCH / 退出码 ≠ STILL_ACTIVE）可接管，EPERM/其他错误视为存活。
    OS 级文件锁（msvcrt/fcntl）在 Goal 5 升级。
    """

    def __init__(self, ws: Workspace) -> None:
        self.lock_path = Path(ws.root) / ".novelos.lock"
        self._token: str | None = None

    def acquire(self) -> None:
        self._token = uuid.uuid4().hex
        payload = json.dumps(
            {"pid": os.getpid(), "owner_token": self._token, "acquired_at": utc_now_iso()},
            ensure_ascii=False,
        )
        for attempt in range(2):
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(payload + "\n")
                return
            except FileExistsError:
                if attempt == 0 and self._takeover_if_dead():
                    continue
                raise NovelosError(
                    ILLEGAL_OPERATION,
                    "另一个 NovelOS 命令正在使用该工作区",
                    exit_code=EXIT_ILLEGAL,
                    hint="稍后重试；确认无其他 novelos 进程后可删除 .novelos.lock",
                )

    def _takeover_if_dead(self) -> bool:
        try:
            holder = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False  # 读不动 → 不接管
        pid = holder.get("pid")
        if not isinstance(pid, int) or _process_alive(pid):
            return False
        with contextlib.suppress(OSError):
            self.lock_path.unlink()
        return True

    def release(self) -> None:
        if self._token is None:
            return
        token = self._token
        self._token = None
        try:
            holder = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if holder.get("owner_token") == token:
            with contextlib.suppress(OSError):
                self.lock_path.unlink()

    def __enter__(self) -> WorkspaceLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class WorkspaceCorruptError(NovelosError):
    """内部层损坏或回滚失败；exit 5 WORKSPACE_CORRUPT。"""

    def __init__(self, message: str) -> None:
        super().__init__(
            WORKSPACE_CORRUPT,
            message,
            exit_code=EXIT_ENV,
            hint="运行 novelos doctor 诊断；不可恢复时从 checkpoint 恢复",
        )


class OutOfBandError(NovelosError):
    """受管层带外修改；exit 2；携带 report 供信封 data。"""

    def __init__(self, report: ScanReport) -> None:
        paths = ", ".join(m["path"] for m in report.blocking_mismatches)
        super().__init__(
            OUT_OF_BAND_WRITE_DETECTED,
            f"检测到受管文件带外修改：{paths}",
            exit_code=EXIT_ILLEGAL,
            hint="Phase 2：从干净状态重跑；必要时从 checkpoint 恢复",
        )
        self.report = report


# 应用序分类：①内部 ②受管 ③decisions ④ledger ⑤manifest（⑥events 单独追加）。
def _apply_rank(rel: str) -> int:
    if rel == ".novelos/decisions.jsonl":
        return 3
    if rel == ".novelos/hash-ledger.yaml":
        return 4
    if rel == ".novelos/internal-manifest.yaml":
        return 5
    if rel.startswith(".novelos/"):
        return 1
    return 2


class WorkspaceTransaction:
    """进程内原子事务：全部写入先缓冲（内存），commit 快照原件 → 按序应用 → 追加事件。

    进程崩溃于应用中途 → 撕裂态由 integrity-scan 判 WORKSPACE_CORRUPT（诚实态；
    journal reconcile 属 Goal 5，不做自动修复）。
    """

    inject: Callable[[str], None] | None = None
    inject_rollback_fail: bool = False  # 测试钩子：强制回滚阶段失败 → 升级损坏

    def __init__(self, ws: Workspace) -> None:
        self._ws = ws
        self._root = Path(ws.root)
        self._files: dict[str, bytes | None] = {}  # rel → 新字节；None = 删除
        self._mkdirs: set[str] = set()
        self._rmdirs: set[str] = set()
        self._events_pending: list[dict] = []
        self._event_base: tuple[int, str] | None = None  # (磁盘事件数, 末事件 hash)

    # -- 缓冲 API -----------------------------------------------------------

    def _normalize(self, rel: str) -> str:
        if rel == "" or rel.startswith("/") or "\\" in rel:
            raise ValueError(f"非法相对路径：{rel!r}")
        parts = rel.split("/")
        if ".." in parts or "." in parts:
            raise ValueError(f"路径不得含 .. / . 分量：{rel!r}")
        return "/".join(parts)

    def write(self, rel: str, data: bytes) -> str:
        """缓冲写文件；返回内容 sha256（供 file_changes / ledger 登记）。"""
        rel = self._normalize(rel)
        if rel == ".novelos/events.jsonl":
            raise ValueError("events.jsonl 只经 append_event/anchor_event 写入")
        self._files[rel] = bytes(data)
        return sha256_hex(data)

    def write_yaml(self, rel: str, obj: object) -> str:
        """缓冲写 YAML（sort_keys/allow_unicode/block 风格，UTF-8/LF）；返回内容 hash。"""
        text = yaml.safe_dump(obj, sort_keys=True, allow_unicode=True, default_flow_style=False)
        return self.write(rel, text.encode("utf-8"))

    def mkdir(self, rel: str) -> None:
        self._mkdirs.add(self._normalize(rel))

    def delete_file(self, rel: str) -> None:
        rel = self._normalize(rel)
        if rel == ".novelos/events.jsonl":
            raise ValueError("events.jsonl 不得经事务删除")
        self._files[rel] = None

    def delete_dir(self, rel: str) -> None:
        """递归缓冲删全部内含文件（原件快照供回滚）。"""
        rel = self._normalize(rel)
        target = self._root / rel
        if target.is_dir():
            for path in sorted(target.rglob("*")):
                if path.is_file():
                    inner = path.relative_to(self._root).as_posix()
                    self._files[inner] = None
            self._rmdirs.add(rel)

    # -- 事件链 -------------------------------------------------------------

    def _chain_state(self) -> tuple[int, str]:
        if self._event_base is None:
            existing = events.read_events(self._ws.events)
            prev = existing[-1]["event_hash"] if existing else events.GENESIS_PREV_HASH
            self._event_base = (len(existing), prev)
        base, prev = self._event_base
        for ev in self._events_pending:
            base += 1
            prev = ev["event_hash"]
        return base, prev

    def append_event(self, **fields: object) -> dict:
        """缓冲一个事件（internal_manifest_hash 缺省 None）；闭合 hash 链。"""
        index, prev = self._chain_state()
        fields.setdefault("internal_manifest_hash", None)
        event = events.compose_event(index=index, prev_hash=prev, **fields)
        self._events_pending.append(event)
        return event

    def anchor_event(self, **fields: object) -> dict:
        """末事件：重算 internal-manifest（现行条目 ⊕ 缓冲 .novelos 内文件 ⊖ 缓冲删除项，
        排除 events.jsonl 与 decisions.jsonl——06 §3.1 三分），缓冲 manifest 写入，
        事件 internal_manifest_hash = hash(manifest 字节)。commit 前最后调用。"""
        current = _read_yaml(self._ws.manifest) if self._ws.manifest.is_file() else None
        files: dict[str, str] = {}
        if isinstance(current, dict):
            stored = current.get("files")
            if isinstance(stored, dict):
                files = {k: v for k, v in stored.items() if isinstance(k, str) and isinstance(v, str)}
        for rel, data in self._files.items():
            if not rel.startswith(".novelos/") or rel in _MANIFEST_EXCLUDE:
                continue
            key = rel[len(".novelos/") :]
            if data is None:
                files.pop(key, None)
            else:
                files[key] = sha256_hex(data)
        manifest_bytes = yaml.safe_dump(
            {"files": files}, sort_keys=True, allow_unicode=True, default_flow_style=False
        ).encode("utf-8")
        self._files[".novelos/internal-manifest.yaml"] = manifest_bytes
        fields["internal_manifest_hash"] = sha256_hex(manifest_bytes)
        return self.append_event(**fields)

    # -- 提交 / 回滚 --------------------------------------------------------

    def _fire(self, stage: str) -> None:
        if self.inject is not None:
            self.inject(stage)

    def commit(self) -> None:
        self._fire("before_apply")
        originals: dict[str, bytes | None] = {}
        for rel in self._files:
            path = self._root / rel
            originals[rel] = path.read_bytes() if path.is_file() else None
        events_path = self._ws.events
        original_events_len: int | None = (
            events_path.stat().st_size if events_path.is_file() else None
        )
        try:
            for rel in sorted(self._mkdirs):
                (self._root / rel).mkdir(parents=True, exist_ok=True)
            for rel in sorted(self._files, key=lambda r: (_apply_rank(r), r)):
                path = self._root / rel
                data = self._files[rel]
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                self._fire(f"after:{rel}")
            for rel in sorted(self._rmdirs, key=lambda r: -r.count("/")):
                shutil.rmtree(self._root / rel, ignore_errors=True)
            self._fire("after_apply")
            self._fire("before_events")
            if self._events_pending:
                blob = "".join(
                    canonical_json(ev).decode("utf-8") + "\n" for ev in self._events_pending
                )
                events_path.parent.mkdir(parents=True, exist_ok=True)
                with events_path.open("ab") as fh:
                    fh.write(blob.encode("utf-8"))
            self._fire("after_events")
        except BaseException as original:
            try:
                self._rollback(originals, original_events_len)
            except Exception as rollback_exc:
                log.error("事务应用失败：%r", original, exc_info=original)
                log.error("回滚亦失败：%r", rollback_exc, exc_info=rollback_exc)
                raise WorkspaceCorruptError(
                    f"事务应用失败且回滚失败：original={original!r} rollback={rollback_exc!r}"
                ) from rollback_exc
            raise

    def _rollback(self, originals: dict[str, bytes | None], events_len: int | None) -> None:
        if self.inject_rollback_fail:
            raise RuntimeError("rollback failure injected")
        for rel, data in originals.items():
            path = self._root / rel
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        events_path = self._ws.events
        if events_len is None:
            events_path.unlink(missing_ok=True)
        else:
            with events_path.open("r+b") as fh:
                fh.truncate(events_len)
        for rel in sorted(self._rmdirs):
            (self._root / rel).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 双层写前检查 + 非递归审计
# ---------------------------------------------------------------------------


def append_out_of_band_audit_under_existing_lock(
    ws: Workspace, mismatches: list[dict]
) -> None:
    """复用已持锁写 OUT_OF_BAND_DETECTED 审计事件（06 §3）。

    绝不复用 guarded_transaction（避免递归写前检查）：不再跑受管层 preflight，
    直接经裸事务锚定现行未变 manifest 并 commit。
    """
    ledger = _read_yaml(ws.ledger) if ws.ledger.is_file() else {}
    entries = ledger.get("entries", []) if isinstance(ledger, dict) else []
    expected_by_path = {e.get("path"): e.get("hash") for e in entries if isinstance(e, dict)}
    file_changes = []
    for m in mismatches:
        path = Path(ws.root) / m["path"]
        file_changes.append(
            {
                "path": m["path"],
                "before_hash": expected_by_path.get(m["path"]),
                "after_hash": hash_file(path) if path.exists() else None,
            }
        )
    tx = WorkspaceTransaction(ws)
    tx.anchor_event(
        type="OUT_OF_BAND_DETECTED",
        transaction_id=events.new_transaction_id(),
        file_changes=file_changes,
        source_mode=None,
    )
    tx.commit()


@contextlib.contextmanager
def guarded_transaction(ws: Workspace) -> Iterator[WorkspaceTransaction]:
    """受保护变更动词的统一入口（init / task open / candidate submit / validate /
    present / decide / checkpoint）：加锁 → 内部层核验（损坏拒绝不写任何事件）
    → 受管层核验（阻断失配 → 审计事件后拒绝）→ yield 事务 → 正常退出 commit。"""
    lock = WorkspaceLock(ws)
    lock.acquire()
    try:
        # 内部层：.novelos/ 不存在 → 空转通过（覆盖 init）。
        if ws.internal_dir.exists():
            report = ScanReport()
            event_by_id = {ev.get("event_id"): ev for ev in events.read_events(ws.events)}
            scan_internal(ws, report, event_by_id)
            if not (report.chain_ok and report.anchor_ok):
                raise WorkspaceCorruptError(
                    f"内部状态损坏：{report.chain_detail or '事件链断裂或锚定失配'}"
                )
        # 受管层：无 ledger → 空转通过。derived_dirty 不阻断（06 §3：标记后继续）。
        if ws.ledger.is_file():
            report = ScanReport()
            event_by_id = {ev.get("event_id"): ev for ev in events.read_events(ws.events)}
            scan_managed(ws, report, event_by_id)
            if report.blocking_mismatches:
                append_out_of_band_audit_under_existing_lock(ws, report.blocking_mismatches)
                raise OutOfBandError(report)
        tx = WorkspaceTransaction(ws)
        try:
            yield tx
        except BaseException:
            raise
        else:
            tx.commit()
    finally:
        lock.release()
