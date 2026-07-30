"""NovelOS workspace: layout, YAML I/O, init.

Frozen shapes: 冻结文档 06 §1（布局）、§3（hash 账本）、§6（事件锚定不变量）、
§8（request ledger）、§3.2（LF/UTF-8/hash 基线）。
"""

from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

import yaml

from novelos import __version__, events
from novelos.events import utc_now_iso
from novelos.protocol import (
    EXIT_ENV,
    EXIT_ILLEGAL,
    ILLEGAL_OPERATION,
    NOT_INITIALIZED,
    PROTOCOL_VERSION,
    REQUEST_ID_CONFLICT,
    WORKSPACE_CORRUPT,
    NovelosError,
    canonical_json,
    sha256_hex,
)

# 冻结文档 06 §1 布局（Phase 2 子集；空目录也创建）
SKELETON_DIRS = (
    "story",
    "story/chapters",
    "state",
    "work",
    "export",
    ".novelos",
    ".novelos/tasks",
    ".novelos/artifacts",
    ".novelos/requests",
    ".novelos/checkpoints",
    ".novelos/runs",
)


def write_yaml(path: Path, obj: object) -> None:
    """Core 一律 LF 行尾写入（冻结文档 06 §3.2）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        yaml.safe_dump(obj, fh, sort_keys=True, allow_unicode=True, default_flow_style=False)


def read_yaml(path: Path) -> object:
    with path.open("r", encoding="utf-8", newline="\n") as fh:
        return yaml.safe_load(fh)


def core_version() -> str:
    try:
        return metadata.version("novelos")
    except metadata.PackageNotFoundError:  # pragma: no cover — 源码直跑兜底
        return __version__


class Workspace:
    """作品目录路径视图。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @property
    def managed_manifest(self) -> Path:
        return self.root / "novelos.yaml"

    @property
    def internal_dir(self) -> Path:
        return self.root / ".novelos"

    @property
    def ledger(self) -> Path:
        return self.internal_dir / "hash-ledger.yaml"

    @property
    def manifest(self) -> Path:
        return self.internal_dir / "internal-manifest.yaml"

    @property
    def events(self) -> Path:
        return self.internal_dir / "events.jsonl"

    @property
    def decisions(self) -> Path:
        return self.internal_dir / "decisions.jsonl"

    @property
    def requests_dir(self) -> Path:
        return self.internal_dir / "requests"

    @property
    def tasks_dir(self) -> Path:
        return self.internal_dir / "tasks"

    @property
    def artifacts_dir(self) -> Path:
        return self.internal_dir / "artifacts"

    @property
    def checkpoints_dir(self) -> Path:
        return self.internal_dir / "checkpoints"

    @property
    def runs_dir(self) -> Path:
        return self.internal_dir / "runs"

    def is_initialized(self) -> bool:
        return self.managed_manifest.is_file()


def open(root: Path, *, require_initialized: bool) -> Workspace:
    """打开 Workspace；损坏（有 .novelos/ 无 novelos.yaml）优先于未初始化报告。"""
    ws = Workspace(root)
    if ws.internal_dir.exists() and not ws.is_initialized():
        raise NovelosError(
            WORKSPACE_CORRUPT,
            "发现 .novelos/ 但缺少 novelos.yaml",
            exit_code=EXIT_ENV,
            hint="运行 novelos doctor 诊断",
        )
    if require_initialized and not ws.is_initialized():
        raise NovelosError(
            NOT_INITIALIZED,
            "工作区未初始化",
            exit_code=EXIT_ILLEGAL,
            hint="先运行 novelos init",
        )
    return ws


def replay_or_none(
    ws: Workspace, command: str, request_id: str | None, arguments_hash: str
) -> dict | None:
    """请求账本重放（冻结文档 04 §1.5 / 06 §8）：同 request_id + command + arguments_hash
    → 返回原响应（不加锁、不写状态）；同 id 携带不同 command/参数 → REQUEST_ID_CONFLICT。"""
    if request_id is None:
        return None
    path = ws.requests_dir / f"{request_id}.json"
    if not path.exists():
        return None
    stored = json.loads(path.read_text(encoding="utf-8"))
    if stored.get("command") == command and stored.get("arguments_hash") == arguments_hash:
        return stored["response"]
    raise NovelosError(
        REQUEST_ID_CONFLICT,
        "同一 request_id 携带不同 command 或参数",
        exit_code=EXIT_ILLEGAL,
        hint="为新的变更调用生成新的 request_id（UUID）",
    )


def write_request_record(
    tx: object,
    ws: Workspace,
    *,
    command: str,
    request_id: str | None,
    arguments_hash: str,
    response: dict,
) -> str | None:
    """经事务写请求记录（requests/* 由 anchor_event 自动收录 manifest）；返回 rel 路径。"""
    if request_id is None:
        return None
    rel = f".novelos/requests/{request_id}.json"
    payload = (
        json.dumps(
            {
                "request_id": request_id,
                "command": command,
                "arguments_hash": arguments_hash,
                "response": response,
                "created_at": utc_now_iso(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    tx.write(rel, payload.encode("utf-8"))  # type: ignore[attr-defined]
    return rel


def init(
    root: Path,
    project_name: str | None,
    *,
    request_id: str | None,
    session_id: str | None,
) -> dict:
    """初始化 Workspace（经 guarded_transaction：根目录锁 + 双层写前检查 + 原子提交）。

    空工作区双层 preflight 空转通过；锚定不变量（06 §6）：manifest 三分排除
    events.jsonl/decisions.jsonl（06 §3.1），末事件 INITIALIZED 携带 manifest hash。
    """
    from novelos.transaction import guarded_transaction  # 延迟导入：transaction → integrity → workspace 环

    root = Path(root)
    ws = Workspace(root)

    if project_name is None:
        project_name = root.resolve().name

    # request ledger 幂等优先（04 §1.5 / 06 §8）：同 request_id 重放返回原响应，即使已初始化。
    arguments_hash = sha256_hex(canonical_json({"project_name": project_name}))
    replayed = replay_or_none(ws, "init", request_id, arguments_hash)
    if replayed is not None:
        return replayed

    if ws.is_initialized():
        raise NovelosError(
            ILLEGAL_OPERATION,
            "工作区已初始化",
            exit_code=EXIT_ILLEGAL,
            hint="如需重建，先删除 novelos.yaml 与 .novelos/",
        )
    if ws.internal_dir.exists():
        raise NovelosError(
            WORKSPACE_CORRUPT,
            "发现 .novelos/ 但缺少 novelos.yaml",
            exit_code=EXIT_ENV,
            hint="运行 novelos doctor 诊断",
        )

    response = {"initialized": True, "workspace_root": str(root.resolve())}

    with guarded_transaction(ws) as tx:
        for rel in SKELETON_DIRS:
            tx.mkdir(rel)

        managed_hash = tx.write_yaml(
            "novelos.yaml",
            {
                "novelos_version": core_version(),
                "protocol_version": PROTOCOL_VERSION,
                "project_name": project_name,
                "created_at": utc_now_iso(),
            },
        )
        tx.write_yaml(
            ".novelos/hash-ledger.yaml",
            {
                "entries": [
                    {
                        "path": "novelos.yaml",
                        "hash": managed_hash,
                        "last_event_id": "ev-000001",
                        "last_artifact_revision": None,
                        "blocking": True,
                    }
                ]
            },
        )
        tx.write(".novelos/decisions.jsonl", b"")
        write_request_record(
            tx,
            ws,
            command="init",
            request_id=request_id,
            arguments_hash=arguments_hash,
            response=response,
        )

        # 末事件：INITIALIZED 为脚手架而非内容，source_mode 为 null（冻结文档 10 §3 seed 检查）
        tx.anchor_event(
            type="INITIALIZED",
            transaction_id=events.new_transaction_id(),
            file_changes=[{"path": "novelos.yaml", "before_hash": None, "after_hash": managed_hash}],
            before_hash=None,
            after_hash=managed_hash,
            source_mode=None,
            session_id=session_id,
        )

    return response
