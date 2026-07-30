"""NovelOS wire protocol: envelope, exit codes, error registry, hash baselines.

Frozen shapes: 冻结文档 04 §1.3（JSON 信封）/ §1.4（退出码）/ §4（错误码注册表）。
Hash baselines: 冻结文档 06 §3.2（SHA-256、规范化 JSON、多文件组合）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

# 版本握手（冻结文档 04 §1.2）
PROTOCOL_VERSION = "1.0"
MIN_EXTENSION_VERSION = "0.1.0"

# 退出码（冻结文档 04 §1.4）
EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_ILLEGAL = 2
EXIT_INTERNAL = 3
EXIT_USAGE = 4
EXIT_ENV = 5

# 错误码注册表（冻结文档 04 §4，Goal 1 子集）。
# USAGE_ERROR 由 04 r6 实现期回写登记（CLI 解析层，退出码 4）。
NOT_INITIALIZED = "NOT_INITIALIZED"
WORKSPACE_CORRUPT = "WORKSPACE_CORRUPT"
CORE_LAUNCHER_NOT_FOUND = "CORE_LAUNCHER_NOT_FOUND"
CORE_VERSION_MISMATCH = "CORE_VERSION_MISMATCH"
ILLEGAL_OPERATION = "ILLEGAL_OPERATION"
OUT_OF_BAND_WRITE_DETECTED = "OUT_OF_BAND_WRITE_DETECTED"
REQUEST_ID_CONFLICT = "REQUEST_ID_CONFLICT"
INTERNAL_ERROR = "INTERNAL_ERROR"
USAGE_ERROR = "USAGE_ERROR"


@dataclass(frozen=True)
class ErrorItem:
    """信封 errors[] 项（冻结文档 04 §1.3）。"""

    code: str
    message: str
    path: str | None = None
    hint: str | None = None


class NovelosError(Exception):
    """带错误码与退出码的领域错误；经 to_item() 进入信封。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        exit_code: int,
        hint: str | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.hint = hint
        self.path = path

    def to_item(self) -> ErrorItem:
        return ErrorItem(code=self.code, message=self.message, path=self.path, hint=self.hint)


def envelope(data: object = None, errors: Sequence[ErrorItem] = ()) -> dict:
    """构造 JSON 信封；path/hint 为 None 时不落键。"""
    items: list[dict] = []
    for err in errors:
        item = asdict(err)
        if item["path"] is None:
            del item["path"]
        if item["hint"] is None:
            del item["hint"]
        items.append(item)
    return {"ok": len(items) == 0, "data": data, "errors": items}


def emit(env: dict) -> None:
    """单个 JSON 文档到 stdout（冻结文档 04 §1.3）。"""
    print(json.dumps(env, ensure_ascii=False))


def _reject_floats(obj: object, where: str = "$") -> None:
    if isinstance(obj, float):
        raise TypeError(f"float values are not allowed in canonical JSON ({where})")
    if isinstance(obj, dict):
        for key, value in obj.items():
            _reject_floats(key, f"{where}.key")
            _reject_floats(value, f"{where}.{key}")
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            _reject_floats(value, f"{where}[{i}]")


def canonical_json(obj: object) -> bytes:
    """RFC 8785 子集：键排序、无赘余空白、UTF-8（冻结文档 06 §3.2）。

    事件域内不允许 float；出现即 TypeError。
    """
    _reject_floats(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    """对文件原始字节计算（冻结文档 06 §3.2 单文件）。"""
    return sha256_hex(Path(path).read_bytes())


def combine_hash(entries: Iterable[tuple[str, str]]) -> str:
    """多文件组合 hash（冻结文档 06 §3.2）。

    entries: (posix 相对路径, sha256:<hex>) 对；每行 ``<hash>  <path>``（两空格），
    按路径字节序排序，UTF-8/LF 文本取 SHA-256。
    """
    pairs = list(entries)
    if not pairs:
        raise ValueError("combine_hash requires at least one entry")
    lines = [f"{h}  {p}" for p, h in sorted(pairs, key=lambda kv: kv[0].encode("utf-8"))]
    return sha256_hex(("\n".join(lines) + "\n").encode("utf-8"))
