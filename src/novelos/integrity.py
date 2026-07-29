"""NovelOS two-layer integrity scanner.

Frozen shapes: 冻结文档 06 §3.1（双层完整性）、冻结文档 10 §4（扫描器规格）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from novelos import events
from novelos.workspace import Workspace, read_yaml
from novelos.protocol import hash_file


@dataclass
class ScanReport:
    scanned_files: int = 0
    blocking_mismatches: list[dict] = field(default_factory=list)
    derived_dirty: list[dict] = field(default_factory=list)
    chain_ok: bool = True
    chain_detail: str = ""
    anchor_ok: bool = True

    def to_data(self) -> dict:
        return {
            "scanned_files": self.scanned_files,
            "blocking_mismatches": self.blocking_mismatches,
            "derived_dirty": self.derived_dirty,
            "chain_ok": self.chain_ok,
            "anchor_ok": self.anchor_ok,
            "chain_detail": self.chain_detail,
        }


def _scan_managed(ws: Workspace, report: ScanReport, event_by_id: dict[str, dict]) -> None:
    """受管作品层：hash-ledger 逐文件核验 + 账本/事件交叉核验。

    Goal 2 的写前扫描（冻结文档 06 §3）复用本函数。
    """
    ledger = read_yaml(ws.ledger) or {}
    for entry in ledger.get("entries", []):
        report.scanned_files += 1
        path = ws.root / entry["path"]
        actual = hash_file(path) if path.exists() else None
        if actual != entry["hash"]:
            item = {
                "path": entry["path"],
                "expected_hash": entry["hash"],
                "actual_hash": actual,
                "last_legitimate_event": entry.get("last_event_id"),
            }
            if entry.get("blocking", True):
                report.blocking_mismatches.append(item)
            else:
                report.derived_dirty.append(item)
        # 交叉核验：账本 last_event_id 事件的 file_changes[path].after_hash == 账本 hash
        # （冻结文档 10 §4 步骤 2：以 last_event_id 为权威）
        event = event_by_id.get(entry.get("last_event_id"))
        if event is None:
            report.chain_ok = False
            report.chain_detail = report.chain_detail or (
                f"ledger entry {entry['path']} references missing event {entry.get('last_event_id')}"
            )
            continue
        changes = {c.get("path"): c for c in event.get("file_changes") or []}
        change = changes.get(entry["path"])
        if change is None or change.get("after_hash") != entry["hash"]:
            report.chain_ok = False
            report.chain_detail = report.chain_detail or (
                f"ledger/event divergence at {entry['path']} (event {event.get('event_id')})"
            )


def _scan_internal(ws: Workspace, report: ScanReport, event_by_id: dict[str, dict]) -> None:
    """内部状态层：事件链、末事件锚定、decisions 绑定、冻结候选内容。"""
    ok, detail = events.verify_chain(ws.events)
    if not ok:
        report.chain_ok = False
        report.chain_detail = report.chain_detail or detail

    # 末事件锚定 internal-manifest.yaml（冻结文档 06 §6 r5 不变量）
    last = events.last_anchored_event(ws.events)
    if (
        last is None
        or last.get("internal_manifest_hash") is None
        or not ws.manifest.is_file()
        or last["internal_manifest_hash"] != hash_file(ws.manifest)
    ):
        report.anchor_ok = False

    # decisions.jsonl 每行绑定一个事件（冻结文档 06 §3.1；Goal 1 文件为空）
    if ws.decisions.is_file():
        with ws.decisions.open("r", encoding="utf-8", newline="\n") as fh:
            for i, raw in enumerate(fh):
                line = raw.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    report.chain_ok = False
                    report.chain_detail = report.chain_detail or f"decisions.jsonl line {i + 1}: invalid JSON"
                    continue
                if record.get("event_id") not in event_by_id:
                    report.chain_ok = False
                    report.chain_detail = report.chain_detail or (
                        f"decisions.jsonl line {i + 1}: unbound event_id {record.get('event_id')}"
                    )

    # 冻结候选内容逐文件核验 meta.yaml.files[].hash（冻结文档 10 §4 步骤 3；Goal 1 无候选）
    if ws.tasks_dir.is_dir():
        for meta_path in ws.tasks_dir.glob("*/candidates/rev-*/meta.yaml"):
            meta = read_yaml(meta_path) or {}
            for file_entry in meta.get("files", []):
                frozen = meta_path.parent / file_entry["path"]
                actual = hash_file(frozen) if frozen.exists() else None
                if actual != file_entry.get("hash"):
                    report.chain_ok = False
                    report.chain_detail = report.chain_detail or (
                        f"frozen candidate content mismatch: {frozen}"
                    )


def scan(ws: Workspace) -> ScanReport:
    """双层完整性扫描（冻结文档 06 §3.1）；只读，不改 Workspace。"""
    report = ScanReport()
    event_by_id = {ev.get("event_id"): ev for ev in events.read_events(ws.events)}
    _scan_managed(ws, report, event_by_id)
    _scan_internal(ws, report, event_by_id)
    return report
