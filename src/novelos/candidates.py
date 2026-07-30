"""NovelOS candidate 领域：submit（LF 规范化 + 路径安全 + 冻结）与 validate（premise-v1）。

冻结文档：04 §3.3/§3.4（submit/validate 语义）、06 §3.2/§4（LF 规范化 hash 基线、
Candidate 存储）、07 §5/§8（premise output contract、生命周期）。
领域函数接收 tx 缓冲写入 + 事件并返回 dict，绝不 tx.commit()（调用方负责）。
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from novelos import events
from novelos.protocol import (
    EXIT_ILLEGAL,
    EXIT_USAGE,
    EXIT_VALIDATION,
    ILLEGAL_OPERATION,
    OUTPUT_PATH_NOT_ALLOWED,
    STALE_INPUT,
    TASK_NOT_FOUND,
    UNEXPECTED_OUTPUT_FILE,
    VALIDATION_FAILED,
    ErrorItem,
    NovelosError,
    canonical_json,
    combine_hash,
    sha256_hex,
)
from novelos.workspace import read_yaml, replay_or_none, write_request_record

if TYPE_CHECKING:
    from novelos.transaction import WorkspaceTransaction
    from novelos.workspace import Workspace

# premise 八小节（冻结文档 07 §5：冻结文件集、内容结构未冻结；判结构不判文学质量）。
# 改节集只改本常量 + instructions 模板。
PREMISE_SECTIONS = (
    "一句话故事钩子",
    "主角是谁",
    "主角主动目标",
    "核心阻力",
    "失败代价",
    "主要读者期待",
    "结局方向",
    "尚待作者决定的问题",
)

# 终态：不得再提交候选。
_TERMINAL_STATUS = ("DONE", "REJECTED")


def _err(code: str, message: str, *, hint: str | None = None, path: str | None = None) -> dict:
    """构造 ErrorItem 同形 dict（落键规则同 protocol.envelope：None 的 path/hint 不落键）。"""
    item = ErrorItem(code=code, message=message, path=path, hint=hint)
    data = asdict(item)
    if data["path"] is None:
        del data["path"]
    if data["hint"] is None:
        del data["hint"]
    return data


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(tx: WorkspaceTransaction, rel: str, obj: object) -> None:
    tx.write(rel, (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _check_path_safety(staging: Path, rel: Path) -> None:
    """staging 内路径安全检查（冻结文档 04 r7：OUTPUT_PATH_NOT_ALLOWED，exit 1）。

    rel 为相对 staging 的路径。绝对路径 / `..` 分量、符号链接 / Windows 联接（reparse point）、
    resolve 后逃逸 staging 子树均拒绝。
    """
    if rel.is_absolute() or ".." in rel.parts:
        raise NovelosError(
            OUTPUT_PATH_NOT_ALLOWED,
            "staging 路径不得逃逸",
            exit_code=EXIT_VALIDATION,
            hint="路径不得逃逸 staging",
            path=rel.as_posix(),
        )
    actual = staging / rel
    if actual.is_symlink():
        raise NovelosError(
            OUTPUT_PATH_NOT_ALLOWED,
            "staging 内禁止符号链接/联接",
            exit_code=EXIT_VALIDATION,
            hint="staging 内禁止符号链接/联接",
            path=rel.as_posix(),
        )
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if reparse:
        try:
            attrs = os.lstat(actual).st_file_attributes  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            attrs = 0
        if attrs & reparse:
            raise NovelosError(
                OUTPUT_PATH_NOT_ALLOWED,
                "staging 内禁止符号链接/联接",
                exit_code=EXIT_VALIDATION,
                hint="staging 内禁止符号链接/联接",
                path=rel.as_posix(),
            )
    resolved = actual.resolve()
    root = staging.resolve()
    if resolved != root and root not in resolved.parents:
        raise NovelosError(
            OUTPUT_PATH_NOT_ALLOWED,
            "staging 路径不得逃逸",
            exit_code=EXIT_VALIDATION,
            hint="路径不得逃逸 staging",
            path=rel.as_posix(),
        )


def _parse_sections(text: str) -> dict[str, str]:
    """解析 `## <节名>` 标题及其正文（至下一个 `## ` 标题前）。"""
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in text.split("\n"):
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf)
            current = line[3:].strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf)
    return sections


def submit_candidate(
    ws: Workspace,
    tx: WorkspaceTransaction,
    *,
    task_id: str,
    request_id: str | None,
    session_id: str | None,
    source_mode: str,
) -> dict:
    """提交候选：路径安全 + 文件集判定 + LF 规范化冻结 + 事件锚定（冻结文档 04 §3.3）。"""
    arguments_hash = sha256_hex(canonical_json({"task_id": task_id, "source_mode": source_mode}))
    replayed = replay_or_none(ws, "candidate submit", request_id, arguments_hash)
    if replayed is not None:
        return replayed

    task_path = ws.tasks_dir / task_id / "task.json"
    if not task_path.is_file():
        raise NovelosError(
            TASK_NOT_FOUND,
            f"任务不存在：{task_id}",
            exit_code=EXIT_USAGE,
            hint="确认 task_id 来自 novelos_next / open_task 返回值",
        )
    task = _read_json(task_path)
    status = task.get("status")
    if status in _TERMINAL_STATUS:
        raise NovelosError(
            ILLEGAL_OPERATION,
            "任务已终态",
            exit_code=EXIT_ILLEGAL,
            hint=f"任务状态 {status}，不得再提交候选",
        )
    if status == "AWAITING_DECISION":
        raise NovelosError(
            ILLEGAL_OPERATION,
            "等待作者决定；REVISE 后方可重新提交",
            exit_code=EXIT_ILLEGAL,
            hint="先经 decide 记录作者决定",
        )

    allowed = list(task.get("allowed_outputs", []))
    staging = ws.root / "work" / task_id

    # 路径安全先行（每条目）；同时收集常规文件集。
    rel_files: list[str] = []
    if staging.is_dir():
        for entry in staging.rglob("*"):
            rel = Path(entry.relative_to(staging).as_posix())
            _check_path_safety(staging, rel)
            if entry.is_file():
                rel_files.append(rel.as_posix())
    rel_files = sorted(rel_files)
    file_set = set(rel_files)

    # 文件集判定（全 exit 1，errors 每项带 path + hint）。
    if not file_set:
        raise NovelosError(
            VALIDATION_FAILED,
            "staging 为空",
            exit_code=EXIT_VALIDATION,
            hint=f"请把 premise.md 写入 work/{task_id}/",
        )
    extra = sorted(file_set - set(allowed))
    if extra:
        raise NovelosError(
            UNEXPECTED_OUTPUT_FILE,
            "staging 含允许集之外的文件",
            exit_code=EXIT_VALIDATION,
            hint=f"允许文件：{allowed}；多余文件：{extra}",
            path=extra[0],
        )
    missing = sorted(set(allowed) - file_set)
    if missing:
        raise NovelosError(
            VALIDATION_FAILED,
            "缺少必需文件",
            exit_code=EXIT_VALIDATION,
            hint=f"缺失文件：{missing}；请把 premise.md 写入 work/{task_id}/",
            path=missing[0],
        )

    # 规范化后冻结（preview hash ≡ commit hash）：UTF-8 读、CRLF/CR → LF、冻结副本。
    new_rev = (task.get("current_candidate_revision") or 0) + 1
    frozen: list[dict] = []
    for rel_file in rel_files:
        raw = (staging / rel_file).read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise NovelosError(
                VALIDATION_FAILED,
                "文件非 UTF-8 文本",
                exit_code=EXIT_VALIDATION,
                hint="以 UTF-8 无 BOM 保存",
                path=rel_file,
            ) from None
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        freeze_rel = f".novelos/tasks/{task_id}/candidates/rev-{new_rev}/{rel_file}"
        file_hash = tx.write(freeze_rel, normalized.encode("utf-8"))
        frozen.append({"path": rel_file, "hash": file_hash})
    content_hash = combine_hash([(f["path"], f["hash"]) for f in frozen])

    meta = {
        "candidate_revision": new_rev,
        "files": frozen,
        "submitted_at": events.utc_now_iso(),
        "validation": None,
        "source_mode": source_mode,
    }
    tx.write_yaml(f".novelos/tasks/{task_id}/candidates/rev-{new_rev}/meta.yaml", meta)

    # task.json：current_candidate_revision=N（status 保持 OPEN）整体重写。
    task["current_candidate_revision"] = new_rev
    _write_json(tx, f".novelos/tasks/{task_id}/task.json", task)

    # metrics：candidate_revisions=N。
    metrics_rel = f".novelos/tasks/{task_id}/metrics.json"
    metrics_path = ws.tasks_dir / task_id / "metrics.json"
    metrics = _read_json(metrics_path) if metrics_path.is_file() else {
        "task_id": task_id,
        "context_files_read": 0,
        "retry_count": 0,
        "candidate_revisions": 0,
        "input_tokens": None,
        "output_tokens": None,
        "cached_tokens": None,
    }
    metrics["candidate_revisions"] = new_rev
    _write_json(tx, metrics_rel, metrics)

    response = {"candidate_revision": new_rev, "content_hash": content_hash, "files": rel_files}
    write_request_record(
        tx,
        ws,
        command="candidate submit",
        request_id=request_id,
        arguments_hash=arguments_hash,
        response=response,
    )

    tx.anchor_event(
        type="CANDIDATE_SUBMITTED",
        transaction_id=events.new_transaction_id(),
        task_id=task_id,
        candidate_revision=new_rev,
        after_hash=content_hash,
        file_changes=[],
        source_mode=source_mode,
        session_id=session_id,
    )
    return response


def validate_task(
    ws: Workspace,
    tx: WorkspaceTransaction,
    *,
    task_id: str,
    revision: int | None,
) -> dict:
    """校验候选（premise-v1）：结构检查 + STALE_INPUT，写回 meta.validation 与 VALIDATED 审计事件。

    纯检查：不改 Task 生命周期、不触受管文件；允许校验旧 revision（冻结文档 04 §3.4）。
    """
    task_path = ws.tasks_dir / task_id / "task.json"
    if not task_path.is_file():
        raise NovelosError(
            TASK_NOT_FOUND,
            f"任务不存在：{task_id}",
            exit_code=EXIT_USAGE,
            hint="确认 task_id 来自 novelos_next / open_task 返回值",
        )
    task = _read_json(task_path)
    if revision is None:
        revision = task.get("current_candidate_revision")
    if revision is None:
        raise NovelosError(
            ILLEGAL_OPERATION,
            "尚无候选可校验",
            exit_code=EXIT_ILLEGAL,
            hint="先 submit 提交候选",
        )
    cand_dir = ws.tasks_dir / task_id / "candidates" / f"rev-{revision}"
    if not cand_dir.is_dir():
        raise NovelosError(
            ILLEGAL_OPERATION,
            "尚无候选可校验",
            exit_code=EXIT_ILLEGAL,
            hint="先 submit 提交候选",
        )

    errors: list[dict] = []
    profile = task.get("validation_profile")
    if profile == "premise-v1":
        premise_path = cand_dir / "premise.md"
        text = premise_path.read_text(encoding="utf-8")
        sections = _parse_sections(text)
        for name in PREMISE_SECTIONS:
            if name not in sections:
                errors.append(
                    _err(
                        VALIDATION_FAILED,
                        f"缺少小节『## {name}』",
                        hint="在 premise.md 补充该小节",
                        path="premise.md",
                    )
                )
            elif sections[name].strip() == "":
                errors.append(
                    _err(
                        VALIDATION_FAILED,
                        f"小节『{name}』内容为空",
                        hint="填写该小节内容",
                        path="premise.md",
                    )
                )

    # STALE_INPUT 通用检查：inputs 当前 accepted hash ≠ 开任务时记录的 input_hashes（premise 空转）。
    input_hashes = task.get("input_hashes", {})
    for ref in task.get("inputs", []):
        artifact_id, _, rev_str = ref.partition("@")
        art_meta = read_yaml(ws.artifacts_dir / artifact_id / "meta.yaml") or {}
        revisions = art_meta.get("revisions", [])
        idx = int(rev_str) - 1
        current_hash = revisions[idx]["content_hash"] if 0 <= idx < len(revisions) else None
        if current_hash != input_hashes.get(ref):
            raise NovelosError(
                STALE_INPUT,
                f"输入已过期：{ref}",
                exit_code=EXIT_VALIDATION,
                hint="重新开任务以消费最新输入版本",
                path=ref,
            )

    valid = len(errors) == 0
    meta_path = cand_dir / "meta.yaml"
    meta = read_yaml(meta_path) or {}
    meta["validation"] = {"valid": valid, "errors": errors, "validated_at": events.utc_now_iso()}
    tx.write_yaml(f".novelos/tasks/{task_id}/candidates/rev-{revision}/meta.yaml", meta)

    if not valid:
        metrics_rel = f".novelos/tasks/{task_id}/metrics.json"
        metrics_path = ws.tasks_dir / task_id / "metrics.json"
        metrics = _read_json(metrics_path) if metrics_path.is_file() else {
            "task_id": task_id,
            "context_files_read": 0,
            "retry_count": 0,
            "candidate_revisions": 0,
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
        }
        metrics["retry_count"] = metrics.get("retry_count", 0) + 1
        _write_json(tx, metrics_rel, metrics)

    tx.anchor_event(
        type="VALIDATED",
        transaction_id=events.new_transaction_id(),
        task_id=task_id,
        candidate_revision=revision,
        file_changes=[],
        source_mode=None,
    )
    return {"valid": valid, "errors": errors}
