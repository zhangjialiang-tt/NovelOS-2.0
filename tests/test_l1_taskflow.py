"""L1: subprocess 六动词契约（Goal 2 premise 链 + 写前扫描 + 锁 + evaluation 门控）。

r5 锚定：每个变更动词（含 validate）后立即 integrity-scan PASS。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.l1

FIXTURES = Path(__file__).parent / "fixtures"
EVAL_ENV = {"NOVELOS_RUN_MODE": "evaluation"}


def run_cli(*args, workspace_dir=None, env_extra=None):
    cmd = [sys.executable, "-m", "novelos", *args]
    if workspace_dir is not None:
        cmd += ["--workspace", str(workspace_dir)]
    env = dict(os.environ)
    env.pop("NOVELOS_RUN_MODE", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", env=env)


def parse_envelope(result):
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"one JSON doc per call; stdout={result.stdout!r} stderr={result.stderr!r}"
    return json.loads(lines[0])


def scan_pass(workspace_dir):
    """r5 锚定：变更动词后立即扫描 PASS。"""
    result = run_cli("integrity-scan", "--json", workspace_dir=workspace_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert parse_envelope(result)["data"]["chain_ok"] is True


def write_valid_premise(workspace_dir):
    staging = Path(workspace_dir) / "work" / "task-001"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "premise.md").write_bytes((FIXTURES / "premise" / "valid.md").read_bytes())


def init_ws(tmp_path) -> Path:
    ws = tmp_path / "novel"
    ws.mkdir()
    result = run_cli("init", "--json", workspace_dir=ws)
    assert result.returncode == 0, result.stdout + result.stderr
    return ws


class TestFullChain:
    def test_six_verbs_accept_chain(self, tmp_path):
        ws = init_ws(tmp_path)

        result = run_cli(
            "task", "open", "--task-type", "premise", "--brief", "记忆当铺", "--json", workspace_dir=ws
        )
        assert result.returncode == 0
        data = parse_envelope(result)["data"]
        assert data["task_id"] == "task-001"
        assert data["staging_path"] == "work/task-001"
        scan_pass(ws)

        write_valid_premise(ws)
        result = run_cli("candidate", "submit", "task-001", "--json", workspace_dir=ws)
        assert result.returncode == 0
        assert parse_envelope(result)["data"]["candidate_revision"] == 1
        scan_pass(ws)

        result = run_cli("validate", "task-001", "--json", workspace_dir=ws)
        assert result.returncode == 0
        assert parse_envelope(result)["data"]["valid"] is True
        scan_pass(ws)  # validate 亦变更动词（写 meta/metrics/manifest + VALIDATED 事件）

        result = run_cli("present", "task-001", "--json", workspace_dir=ws)
        assert result.returncode == 0
        pending = parse_envelope(result)["data"]["pending_decision"]
        nonce = pending["nonce"]
        assert len(nonce) == 16
        scan_pass(ws)

        result = run_cli(
            "decide", "task-001",
            "--revision", "1", "--nonce", nonce, "--decision", "accept",
            "--json", workspace_dir=ws,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        data = parse_envelope(result)["data"]
        assert data["task_status"] == "DONE"
        assert data["commit"]["artifact_revisions"] == ["premise@1"]
        story = ws / "story" / "premise.md"
        assert story.is_file()
        assert story.read_bytes() == (FIXTURES / "premise" / "valid.md").read_bytes()
        scan_pass(ws)

        result = run_cli("checkpoint", "--json", workspace_dir=ws)
        assert result.returncode == 0
        data = parse_envelope(result)["data"]
        assert data["checkpoint_id"] == "cp-001"
        assert data["accepted_artifact_refs"] == ["premise@1"]
        scan_pass(ws)


class TestNegativePaths:
    def test_submit_task_not_found_exit_4(self, tmp_path):
        ws = init_ws(tmp_path)
        result = run_cli("candidate", "submit", "task-999", "--json", workspace_dir=ws)
        assert result.returncode == 4
        assert parse_envelope(result)["errors"][0]["code"] == "TASK_NOT_FOUND"

    def test_decide_without_present_exit_2(self, tmp_path):
        ws = init_ws(tmp_path)
        run_cli("task", "open", "--task-type", "premise", "--brief", "想法", "--json", workspace_dir=ws)
        result = run_cli(
            "decide", "task-001", "--revision", "1", "--nonce", "x" * 16, "--decision", "accept",
            "--json", workspace_dir=ws,
        )
        assert result.returncode == 2
        assert parse_envelope(result)["errors"][0]["code"] == "NO_PENDING_DECISION"

    def test_out_of_band_task_open_exit_2_with_audit(self, tmp_path):
        ws = init_ws(tmp_path)
        with (ws / "novelos.yaml").open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("# 带外\n")
        result = run_cli(
            "task", "open", "--task-type", "premise", "--brief", "想法", "--json", workspace_dir=ws
        )
        assert result.returncode == 2
        env = parse_envelope(result)
        assert env["errors"][0]["code"] == "OUT_OF_BAND_WRITE_DETECTED"
        assert env["data"]["blocking_mismatches"], "信封 data 携带扫描报告"
        events_path = ws / ".novelos" / "events.jsonl"
        types = [json.loads(ln)["type"] for ln in events_path.read_text(encoding="utf-8").splitlines()]
        assert types.count("OUT_OF_BAND_DETECTED") == 1

    def test_internal_corruption_submit_exit_5_no_new_events(self, tmp_path):
        ws = init_ws(tmp_path)
        run_cli("task", "open", "--task-type", "premise", "--brief", "想法", "--json", workspace_dir=ws)
        staging = ws / "work" / "task-001"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "premise.md").write_bytes(b"c\n")
        events_path = ws / ".novelos" / "events.jsonl"
        lines = events_path.read_text(encoding="utf-8").splitlines()
        ev = json.loads(lines[-1])
        ev["type"] = "TAMPERED"
        lines[-1] = json.dumps(ev, ensure_ascii=False)
        events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = run_cli("candidate", "submit", "task-001", "--json", workspace_dir=ws)
        assert result.returncode == 5
        assert parse_envelope(result)["errors"][0]["code"] == "WORKSPACE_CORRUPT"
        new_lines = events_path.read_text(encoding="utf-8").splitlines()
        assert len(new_lines) == len(lines), "损坏拒绝不写任何事件"

    def test_fixture_requires_evaluation_env(self, tmp_path):
        ws = init_ws(tmp_path)
        run_cli("task", "open", "--task-type", "premise", "--brief", "想法", "--json", workspace_dir=ws)
        write_valid_premise(ws)

        # submit DETERMINISTIC_FIXTURE 无 evaluation env → ILLEGAL_OPERATION
        result = run_cli(
            "candidate", "submit", "task-001", "--source-mode", "DETERMINISTIC_FIXTURE",
            "--json", workspace_dir=ws,
        )
        assert result.returncode == 2
        assert parse_envelope(result)["errors"][0]["code"] == "ILLEGAL_OPERATION"

        # 有 evaluation env → 成功
        result = run_cli(
            "candidate", "submit", "task-001", "--source-mode", "DETERMINISTIC_FIXTURE",
            "--json", workspace_dir=ws, env_extra=EVAL_ENV,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        # decide --fixture 无 evaluation env → ILLEGAL_OPERATION
        result = run_cli(
            "decide", "task-001", "--revision", "1",
            "--fixture", str(FIXTURES / "decisions" / "accept-premise.json"),
            "--source", "TEST_FIXTURE", "--json", workspace_dir=ws,
        )
        assert result.returncode == 2
        assert parse_envelope(result)["errors"][0]["code"] == "ILLEGAL_OPERATION"

    def test_fixture_source_pairing_usage_errors(self, tmp_path):
        ws = init_ws(tmp_path)
        # --fixture 无 --source TEST_FIXTURE → USAGE_ERROR
        result = run_cli(
            "decide", "task-001", "--revision", "1",
            "--fixture", str(FIXTURES / "decisions" / "accept-premise.json"),
            "--json", workspace_dir=ws, env_extra=EVAL_ENV,
        )
        assert result.returncode == 4
        assert parse_envelope(result)["errors"][0]["code"] == "USAGE_ERROR"
        # --fixture 文件不存在 → USAGE_ERROR
        result = run_cli(
            "decide", "task-001", "--revision", "1",
            "--fixture", str(tmp_path / "nope.json"), "--source", "TEST_FIXTURE",
            "--json", workspace_dir=ws, env_extra=EVAL_ENV,
        )
        assert result.returncode == 4
        assert "fixture" in parse_envelope(result)["errors"][0]["message"]

    def test_lock_held_command_exit_2(self, tmp_path):
        ws = init_ws(tmp_path)
        holder_code = (
            "from novelos.workspace import Workspace;"
            "from novelos.transaction import WorkspaceLock;"
            f"l = WorkspaceLock(Workspace(r'{ws}'));"
            "l.acquire();"
            "print('locked', flush=True);"
            "import time; time.sleep(30)"
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", holder_code],
            stdout=subprocess.PIPE,
            encoding="utf-8",
        )
        try:
            line = holder.stdout.readline()
            assert "locked" in line
            result = run_cli(
                "task", "open", "--task-type", "premise", "--brief", "想法",
                "--json", workspace_dir=ws,
            )
            assert result.returncode == 2
            err = parse_envelope(result)["errors"][0]
            assert err["code"] == "ILLEGAL_OPERATION"
            assert "占用" in err["message"] or "使用" in err["message"]
        finally:
            holder.kill()
            holder.wait()
