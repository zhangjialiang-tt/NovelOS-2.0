"""NovelOS CLI: version / doctor / init / status / next / integrity-scan.

Frozen contract: 冻结文档 04 §1.3（--json 单信封）、§1.4（退出码）、§1.5（--request-id）、
§2（init/status/next 数据字段）、§4（错误码）、§5（动词与通用标志）。
人类文本输出为未冻结便利；冻结契约是 --json 信封。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from pathlib import Path

from novelos import candidates, checkpoints, decisions, events, integrity, tasks, transaction, workspace
from novelos.protocol import (
    EXIT_ENV,
    EXIT_ILLEGAL,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_USAGE,
    ILLEGAL_OPERATION,
    INTERNAL_ERROR,
    MIN_EXTENSION_VERSION,
    NOT_INITIALIZED,
    OUT_OF_BAND_WRITE_DETECTED,
    PROTOCOL_VERSION,
    USAGE_ERROR,
    WORKSPACE_CORRUPT,
    ErrorItem,
    NovelosError,
    envelope,
    emit,
    hash_file,
)
from novelos.workspace import Workspace, core_version, read_yaml

log = logging.getLogger("novelos")


class _UsageErrorParser(argparse.ArgumentParser):
    """argparse 用法错误 → USAGE_ERROR 信封 + 退出码 4（冻结文档 04 §4，04 r6 登记）。"""

    def error(self, message: str) -> None:  # noqa: D102 — argparse override
        raise NovelosError(
            USAGE_ERROR,
            message,
            exit_code=EXIT_USAGE,
            hint="运行 novelos <command> --help 查看用法",
        )


def _common_flags() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    # default=SUPPRESS：主解析器与子解析器共享同名标志而不互相覆盖
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="输出单个 JSON 信封到 stdout")
    common.add_argument("--workspace", default=argparse.SUPPRESS, help="作品目录（缺省为当前目录）")
    common.add_argument("--quiet", action="store_true", default=argparse.SUPPRESS, help="压缩 stderr 日志")
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common_flags()
    parser = _UsageErrorParser(prog="novelos", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", parents=[common], help="Core 与协议版本")
    sub.add_parser("doctor", parents=[common], help="安装诊断（Core 层）")

    init_parser = sub.add_parser("init", parents=[common], help="初始化 Workspace")
    init_parser.add_argument("--project-name", default=None, help="项目名；缺省取目录名")
    init_parser.add_argument("--request-id", default=None, help="幂等键（UUID）")

    sub.add_parser("status", parents=[common], help="状态板数据")
    sub.add_parser("next", parents=[common], help="下一步建议")
    sub.add_parser("integrity-scan", parents=[common], help="双层完整性扫描")

    task_p = sub.add_parser("task", parents=[common], help="任务管理")
    task_sub = task_p.add_subparsers(dest="task_command", required=True)
    task_open = task_sub.add_parser("open", parents=[common], help="创建或恢复创作任务")
    task_open.add_argument("--task-type", required=True, help="任务类型（当前仅 premise）")
    task_open.add_argument("--subject", default=None, help="任务主题；缺省由 Core 取值")
    task_open.add_argument("--brief", default=None, help="用户故事想法摘要（创建时必需）")
    task_open.add_argument("--target-artifact-ref", default=None, help="Change Task 主目标；premise 不接受（04 §2 冻结参数）")
    task_open.add_argument("--request-id", default=None, help="幂等键（UUID）")

    candidate_p = sub.add_parser("candidate", parents=[common], help="候选管理")
    candidate_sub = candidate_p.add_subparsers(dest="candidate_command", required=True)
    candidate_submit = candidate_sub.add_parser("submit", parents=[common], help="提交候选")
    candidate_submit.add_argument("task_id", help="任务 id")
    candidate_submit.add_argument("--request-id", default=None, help="幂等键（UUID）")
    candidate_submit.add_argument(
        "--source-mode",
        choices=("REAL_AGENT", "DETERMINISTIC_FIXTURE"),
        default="REAL_AGENT",
        help="候选来源（01 §9.1 落点标记；DETERMINISTIC_FIXTURE 仅 evaluation 运行）",
    )

    validate_p = sub.add_parser("validate", parents=[common], help="校验候选（领域纯检查，效果幂等）")
    validate_p.add_argument("task_id", help="任务 id")
    validate_p.add_argument("--revision", type=int, default=None, help="候选版本号；缺省当前候选")

    present_p = sub.add_parser("present", parents=[common], help="呈现候选待作者决定")
    present_p.add_argument("task_id", help="任务 id")
    present_p.add_argument("--revision", type=int, default=None, help="候选版本号；缺省当前候选")
    present_p.add_argument("--request-id", default=None, help="幂等键（UUID）")

    # decide 为一次性命令（04 §1.5）：不经 --request-id 重放；重复 nonce 返回 DECISION_NONCE_CONSUMED。
    decide_p = sub.add_parser("decide", parents=[common], help="记录作者决定（一次性，不经重放）")
    decide_p.add_argument("task_id", help="任务 id")
    decide_p.add_argument("--revision", type=int, required=True, help="候选版本号")
    decide_p.add_argument("--nonce", default=None, help="pending 决定机会 nonce（交互路径）")
    decide_p.add_argument("--decision", choices=("accept", "revise", "reject"), default=None, help="决定值（交互路径；fixture 分支以文件为准）")
    decide_p.add_argument("--author-note", default=None, help="作者意见（REVISE 进下一轮工作包）")
    decide_p.add_argument("--fixture", default=None, help="决定 fixture 文件（evaluation 分支）")
    decide_p.add_argument("--source", choices=("INTERACTIVE_UI", "TEST_FIXTURE"), default="INTERACTIVE_UI", help="决定来源")

    checkpoint_p = sub.add_parser("checkpoint", parents=[common], help="保存进度检查点")
    checkpoint_p.add_argument("--label", default=None, help="检查点标签")
    checkpoint_p.add_argument("--request-id", default=None, help="幂等键（UUID）")
    return parser


# ---------------------------------------------------------------------------
# 命令实现。处理器返回 (data, exit_code, error_item_or_None)。
# ---------------------------------------------------------------------------


def _cmd_version(args: argparse.Namespace, ws_root: Path) -> tuple[dict, int, ErrorItem | None]:
    data = {
        "core_version": core_version(),
        "protocol_version": PROTOCOL_VERSION,
        "min_extension_version": MIN_EXTENSION_VERSION,
    }
    return data, EXIT_OK, None


def _pi_agent_dir() -> Path:
    return Path(os.environ.get("PI_AGENT_DIR") or (Path.home() / ".pi" / "agent"))


def _settings_paths(pi_agent_dir: Path, key: str) -> list[Path]:
    settings = pi_agent_dir / "settings.json"
    if not settings.is_file():
        return []
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    entries = data.get(key)
    if not isinstance(entries, list):
        return []
    return [Path(str(e)) for e in entries if isinstance(e, str)]


def _check_skill(pi_agent_dir: Path) -> tuple[bool, str]:
    direct = pi_agent_dir / "skills" / "novelos" / "SKILL.md"
    if direct.is_file():
        return True, str(direct)
    for base in _settings_paths(pi_agent_dir, "skills"):
        candidate = base / "novelos" / "SKILL.md"
        if candidate.is_file():
            return True, str(candidate)
    return False, f"未在 {pi_agent_dir}/skills/novelos/ 或 settings.json skills 路径找到 SKILL.md"


def _check_extension(pi_agent_dir: Path) -> tuple[bool, str]:
    for rel in ("extensions/novelos/index.ts", "extensions/novelos.ts"):
        direct = pi_agent_dir / rel
        if direct.is_file():
            return True, str(direct)
    for base in _settings_paths(pi_agent_dir, "extensions"):
        for rel in ("novelos/index.ts", "novelos.ts"):
            candidate = base / rel
            if candidate.is_file():
                return True, str(candidate)
    return False, f"未在 {pi_agent_dir}/extensions/novelos/ 或 settings.json extensions 路径找到扩展"


def _cmd_doctor(args: argparse.Namespace, ws_root: Path) -> tuple[dict, int, ErrorItem | None]:
    pi_agent_dir = _pi_agent_dir()
    py_ok = sys.version_info >= (3, 11)
    py_detail = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    skill_ok, skill_detail = _check_skill(pi_agent_dir)
    ext_ok, ext_detail = _check_extension(pi_agent_dir)
    checks = [
        {
            "id": "python_version",
            "ok": py_ok,
            "detail": py_detail,
            "hint": None if py_ok else "升级到 Python 3.11+",
        },
        {
            "id": "skill_placement",
            "ok": skill_ok,
            "detail": skill_detail,
            "hint": None if skill_ok else "运行 python scripts/install.py",
        },
        {
            "id": "extension_placement",
            "ok": ext_ok,
            "detail": ext_detail,
            "hint": None if ext_ok else "运行 python scripts/install.py",
        },
        {
            "id": "protocol_info",
            "ok": True,
            "detail": f"core {core_version()} / protocol {PROTOCOL_VERSION}",
            "hint": None,
        },
    ]
    all_ok = all(c["ok"] for c in checks)
    data = {
        "checks": checks,
        "all_ok": all_ok,
        "core_version": core_version(),
        "protocol_version": PROTOCOL_VERSION,
    }
    return data, (EXIT_OK if all_ok else EXIT_ENV), None


def _cmd_init(args: argparse.Namespace, ws_root: Path) -> tuple[dict, int, ErrorItem | None]:
    project_name = args.project_name
    if project_name is not None and project_name.strip() == "":
        raise NovelosError(
            USAGE_ERROR,
            "--project-name 不能为空字符串",
            exit_code=EXIT_USAGE,
            hint="省略 --project-name 使用目录名，或提供非空项目名",
        )
    data = workspace.init(
        ws_root,
        project_name,
        request_id=args.request_id,
        session_id=os.environ.get("NOVELOS_SESSION_ID"),
    )
    return data, EXIT_OK, None


def _health_gate(ws: Workspace) -> None:
    """只读命令的内部健康核验；损坏 → WORKSPACE_CORRUPT 退出码 5。"""
    ok, detail = events.verify_chain(ws.events)
    if not ok:
        raise NovelosError(
            WORKSPACE_CORRUPT,
            f"事件链损坏：{detail}",
            exit_code=EXIT_ENV,
            hint="运行 novelos doctor 诊断；必要时从 checkpoint 恢复",
        )
    last = events.last_anchored_event(ws.events)
    if (
        last is None
        or last.get("internal_manifest_hash") is None
        or not ws.manifest.is_file()
        or last["internal_manifest_hash"] != hash_file(ws.manifest)
    ):
        raise NovelosError(
            WORKSPACE_CORRUPT,
            "内部清单锚定失配",
            exit_code=EXIT_ENV,
            hint="运行 novelos doctor 诊断；必要时从 checkpoint 恢复",
        )


def _cmd_status(args: argparse.Namespace, ws_root: Path) -> tuple[dict, int, ErrorItem | None]:
    ws = workspace.open(ws_root, require_initialized=False)
    if not ws.is_initialized():
        data = {
            "initialized": False,
            "project": None,
            "stage": None,
            "completed": [],
            "issues": [],
            "legal_actions": ["init"],
        }
        return data, EXIT_OK, None
    _health_gate(ws)
    manifest = read_yaml(ws.managed_manifest) or {}
    stage = "initialized"
    completed: list[str] = []
    legal_actions: list[str] = ["premise"]
    if _premise_accepted(ws):
        stage = "premise_accepted"
        completed = ["故事核心方向"]
        legal_actions = []
    elif _active_premise_task(ws) is not None:
        stage = "premise_in_progress"
        legal_actions = []
    data = {
        "initialized": True,
        "project": manifest.get("project_name"),
        "stage": stage,
        "completed": completed,
        "issues": [],
        "legal_actions": legal_actions,
    }
    return data, EXIT_OK, None


def _cmd_next(args: argparse.Namespace, ws_root: Path) -> tuple[dict, int, ErrorItem | None]:
    """数据字段 suggested_action/task_type/subject/reason 见冻结文档 04 §2；
    增补 reason_code / user_message：机器可读码 + 可原样呈现的用户文案，
    Extension 与 Agent 不必解析自由文本。"""
    ws = workspace.open(ws_root, require_initialized=False)
    if not ws.is_initialized():
        data = {
            "suggested_action": "init",
            "task_type": None,
            "subject": None,
            "reason": "工作区未初始化",
            "reason_code": "NOT_INITIALIZED",
            "user_message": "还没有作品。要开始新故事吗？",
        }
        return data, EXIT_OK, None
    _health_gate(ws)
    task = _active_premise_task(ws)
    if task is not None:
        data = {
            "suggested_action": "continue_task",
            "task_type": "premise",
            "subject": task.get("subject"),
            "task_id": task.get("task_id"),
            "package_path": f".novelos/tasks/{task.get('task_id')}",
            "staging_path": f"work/{task.get('task_id')}",
            "reason": f"premise 任务状态 {task.get('status')}，继续创作并提交候选",
            "reason_code": "TASK_IN_PROGRESS",
            "user_message": "故事核心任务进行中，请按任务工作包继续创作并提交候选。",
        }
        return data, EXIT_OK, None
    if _premise_accepted(ws):
        data = {
            "suggested_action": None,
            "task_type": None,
            "subject": None,
            "reason": "故事核心已确定；当前版本尚未开放故事规划。",
            "reason_code": "NO_ACTION_IMPLEMENTED",
            "user_message": "故事核心已确定。当前版本尚未开放故事规划。",
        }
        return data, EXIT_OK, None
    data = {
        "suggested_action": "open_task",
        "task_type": "premise",
        "subject": "故事核心方向",
        "reason": "工作区已初始化，尚未确定故事核心",
        "reason_code": "PREMISE_READY",
        "user_message": "下一步：确定故事核心（创建 Story Brief）。",
    }
    return data, EXIT_OK, None


def _cmd_integrity_scan(args: argparse.Namespace, ws_root: Path) -> tuple[dict, int, ErrorItem | None]:
    ws = workspace.open(ws_root, require_initialized=True)
    report = integrity.scan(ws)
    data = report.to_data()
    if not (report.chain_ok and report.anchor_ok):
        return (
            data,
            EXIT_ENV,
            ErrorItem(
                WORKSPACE_CORRUPT,
                f"内部状态损坏：{report.chain_detail or '事件链断裂或锚定失配'}",
                hint="运行 novelos doctor 诊断；必要时从 checkpoint 恢复",
            ),
        )
    if report.blocking_mismatches:
        paths = ", ".join(m["path"] for m in report.blocking_mismatches)
        return (
            data,
            EXIT_ILLEGAL,
            ErrorItem(
                OUT_OF_BAND_WRITE_DETECTED,
                f"检测到受管文件带外修改：{paths}",
                hint="Phase 2：从干净状态重跑；必要时从 checkpoint 恢复",
            ),
        )
    return data, EXIT_OK, None


# ---------------------------------------------------------------------------
# premise 状态探针与 Goal 2 六动词（领域实现见 tasks/candidates/decisions/checkpoints）
# ---------------------------------------------------------------------------


def _read_task_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _premise_accepted(ws: Workspace) -> bool:
    meta_path = ws.artifacts_dir / "premise" / "meta.yaml"
    if not meta_path.is_file():
        return False
    meta = read_yaml(meta_path) or {}
    return bool(meta.get("accepted"))


def _active_premise_task(ws: Workspace) -> dict | None:
    """首个非终态 premise 任务（task_id 序）；无则 None。"""
    if not ws.tasks_dir.is_dir():
        return None
    for task_dir in sorted(ws.tasks_dir.glob("task-*")):
        task_file = task_dir / "task.json"
        if not task_file.is_file():
            continue
        task = _read_task_json(task_file)
        if task.get("task_type") == "premise" and task.get("status") in ("OPEN", "AWAITING_DECISION"):
            return task
    return None


def _session_id() -> str | None:
    return os.environ.get("NOVELOS_SESSION_ID")


def _require_evaluation(what: str) -> None:
    """02 §9：fixture/测试来源仅 evaluation 运行接受（缺省 interactive = 03 §4 G1）。"""
    if os.environ.get("NOVELOS_RUN_MODE") != "evaluation":
        raise NovelosError(
            ILLEGAL_OPERATION,
            f"{what} 仅 evaluation 运行可接受",
            exit_code=EXIT_ILLEGAL,
            hint="fixture/测试来源仅限 evaluation 运行（NOVELOS_RUN_MODE=evaluation）",
        )


def _cmd_task(args: argparse.Namespace, ws_root: Path) -> tuple[dict, int, ErrorItem | None]:
    ws = workspace.open(ws_root, require_initialized=True)
    if args.task_command == "open":
        with transaction.guarded_transaction(ws) as tx:
            data = tasks.open_task(
                ws,
                tx,
                task_type=args.task_type,
                subject=args.subject,
                brief=args.brief,
                target_artifact_ref=args.target_artifact_ref,
                request_id=args.request_id,
                session_id=_session_id(),
            )
        return data, EXIT_OK, None
    raise AssertionError(f"unreachable task_command: {args.task_command!r}")


def _cmd_candidate(args: argparse.Namespace, ws_root: Path) -> tuple[dict, int, ErrorItem | None]:
    ws = workspace.open(ws_root, require_initialized=True)
    if args.candidate_command == "submit":
        if args.source_mode == "DETERMINISTIC_FIXTURE":
            _require_evaluation("--source-mode DETERMINISTIC_FIXTURE")
        with transaction.guarded_transaction(ws) as tx:
            data = candidates.submit_candidate(
                ws,
                tx,
                task_id=args.task_id,
                request_id=args.request_id,
                session_id=_session_id(),
                source_mode=args.source_mode,
            )
        return data, EXIT_OK, None
    raise AssertionError(f"unreachable candidate_command: {args.candidate_command!r}")


def _cmd_validate(args: argparse.Namespace, ws_root: Path) -> tuple[dict, int, ErrorItem | None]:
    ws = workspace.open(ws_root, require_initialized=True)
    with transaction.guarded_transaction(ws) as tx:
        data = candidates.validate_task(ws, tx, task_id=args.task_id, revision=args.revision)
    return data, EXIT_OK, None


def _cmd_present(args: argparse.Namespace, ws_root: Path) -> tuple[dict, int, ErrorItem | None]:
    ws = workspace.open(ws_root, require_initialized=True)
    with transaction.guarded_transaction(ws) as tx:
        data = decisions.present(
            ws,
            tx,
            task_id=args.task_id,
            revision=args.revision,
            request_id=args.request_id,
            session_id=_session_id(),
        )
    return data, EXIT_OK, None


def _cmd_decide(args: argparse.Namespace, ws_root: Path) -> tuple[dict, int, ErrorItem | None]:
    fixture = args.fixture
    source = args.source
    if fixture is not None:
        _require_evaluation("--fixture")
        if source != "TEST_FIXTURE":
            raise NovelosError(
                USAGE_ERROR,
                "--fixture 必须与 --source TEST_FIXTURE 同现",
                exit_code=EXIT_USAGE,
                hint="fixture 决定走 evaluation 分支：--fixture <path> --source TEST_FIXTURE",
            )
        if not Path(fixture).is_file():
            raise NovelosError(
                USAGE_ERROR,
                "fixture 文件不存在",
                exit_code=EXIT_USAGE,
                hint=f"检查路径：{fixture}",
            )
    elif source == "TEST_FIXTURE":
        raise NovelosError(
            USAGE_ERROR,
            "--source TEST_FIXTURE 必须与 --fixture 同现",
            exit_code=EXIT_USAGE,
            hint="fixture 决定需显式 --fixture <path>",
        )
    decision = args.decision.upper() if isinstance(args.decision, str) else args.decision
    if fixture is None and decision is None:
        raise NovelosError(
            USAGE_ERROR,
            "交互决定需要 --decision（accept|revise|reject）",
            exit_code=EXIT_USAGE,
            hint="作者决定经 UI 中介；CLI 直调需显式 --decision",
        )
    ws = workspace.open(ws_root, require_initialized=True)
    with transaction.guarded_transaction(ws) as tx:
        data = decisions.decide(
            ws,
            tx,
            task_id=args.task_id,
            revision=args.revision,
            nonce=args.nonce,
            decision=decision,
            author_note=args.author_note,
            source=source,
            fixture=fixture,
            session_id=_session_id(),
        )
    return data, EXIT_OK, None


def _cmd_checkpoint(args: argparse.Namespace, ws_root: Path) -> tuple[dict, int, ErrorItem | None]:
    ws = workspace.open(ws_root, require_initialized=True)
    with transaction.guarded_transaction(ws) as tx:
        data = checkpoints.checkpoint(
            ws,
            tx,
            label=args.label,
            request_id=args.request_id,
            session_id=_session_id(),
        )
    return data, EXIT_OK, None


_HANDLERS = {
    "version": _cmd_version,
    "doctor": _cmd_doctor,
    "init": _cmd_init,
    "status": _cmd_status,
    "next": _cmd_next,
    "integrity-scan": _cmd_integrity_scan,
    "task": _cmd_task,
    "candidate": _cmd_candidate,
    "validate": _cmd_validate,
    "present": _cmd_present,
    "decide": _cmd_decide,
    "checkpoint": _cmd_checkpoint,
}


# ---------------------------------------------------------------------------
# 人类文本渲染（未冻结便利）
# ---------------------------------------------------------------------------

_STAGE_HUMAN = {
    "initialized": "已初始化",
    "premise_in_progress": "故事核心创作中",
    "premise_accepted": "故事核心已确定",
}


def _render_human(command: str, data: dict) -> str:
    if command == "version":
        return f"novelos {data['core_version']} (protocol {data['protocol_version']})"
    if command == "doctor":
        lines = []
        for check in data["checks"]:
            mark = "ok" if check["ok"] else "FAIL"
            line = f"[{mark}] {check['id']}: {check['detail']}"
            if check["hint"]:
                line += f"（{check['hint']}）"
            lines.append(line)
        lines.append(f"all_ok: {data['all_ok']}")
        return "\n".join(lines)
    if command == "init":
        return f"已初始化：{data['workspace_root']}"
    if command == "status":
        if not data["initialized"]:
            return "作品尚未初始化。运行 novelos init 初始化。"
        stage = _STAGE_HUMAN.get(data["stage"], data["stage"])
        completed = "、".join(data["completed"]) or "（无）"
        issues = "、".join(data["issues"]) or "无阻塞"
        return (
            f"作品：《{data['project']}》\n"
            f"当前阶段：{stage}\n"
            f"已完成：{completed}\n"
            f"当前问题：{issues}"
        )
    if command == "next":
        return f"建议动作：{data['user_message']}"
    if command == "integrity-scan":
        return (
            f"扫描 {data['scanned_files']} 个受管文件；"
            f"阻断失配 {len(data['blocking_mismatches'])}；"
            f"派生脏 {len(data['derived_dirty'])}；"
            f"事件链 {'ok' if data['chain_ok'] else 'BROKEN'}；"
            f"锚定 {'ok' if data['anchor_ok'] else 'BROKEN'}"
        )
    return json.dumps(data, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台/管道默认编码随系统代码页（如 cp936）；强制 UTF-8 输出，
    # 与 Extension 侧 utf8 解码闭环（不依赖宿主终端代码页）。
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):  # 流不可配置（如被替换对象）时忽略
                pass
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except NovelosError as exc:  # 用法错误：一律信封（此时 --json 位置未知）
        emit(envelope(None, [exc.to_item()]))
        return exc.exit_code

    if getattr(args, "quiet", False):
        logging.getLogger().setLevel(logging.WARNING)
    use_json = getattr(args, "json", False)
    ws_root = Path(getattr(args, "workspace", os.getcwd()))

    try:
        data, code, err = _HANDLERS[args.command](args, ws_root)
    except transaction.OutOfBandError as exc:  # 受管层带外：信封 data = 扫描报告（06 §3）
        emit(envelope(exc.report.to_data(), [exc.to_item()]))
        return exc.exit_code
    except NovelosError as exc:
        emit(envelope(None, [exc.to_item()]))
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 — 顶层兜底
        traceback.print_exc()
        log.error("internal error: %s", exc)
        emit(
            envelope(
                None,
                [
                    ErrorItem(
                        INTERNAL_ERROR,
                        f"未分类内部错误：{exc}",
                        hint="查看 stderr 追踪信息；运行 novelos doctor",
                    )
                ],
            )
        )
        return EXIT_INTERNAL

    if err is not None:
        emit(envelope(data, [err]))
        return code
    if use_json:
        emit(envelope(data))
    else:
        print(_render_human(args.command, data))
    return code
