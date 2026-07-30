"""L1: subprocess CLI contract — envelope, exit codes, anchoring, doctor, request-id."""

import json
import os
import subprocess
import sys
import uuid

import pytest

pytestmark = pytest.mark.l1


def run_cli(*args, workspace_dir=None, env_extra=None):
    cmd = [sys.executable, "-m", "novelos", *args]
    if workspace_dir is not None:
        cmd += ["--workspace", str(workspace_dir)]
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", env=env)


def parse_envelope(result):
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"stdout must carry exactly one JSON doc, got: {result.stdout!r}"
    env = json.loads(lines[0])
    assert set(env) == {"ok", "data", "errors"}
    return env


class TestVersion:
    def test_version_outside_any_workspace(self, tmp_path):
        result = run_cli("version", "--json", workspace_dir=tmp_path)
        assert result.returncode == 0
        env = parse_envelope(result)
        assert env["ok"] is True
        assert env["data"]["core_version"]
        assert env["data"]["protocol_version"] == "1.0"
        assert env["data"]["min_extension_version"]


class TestEnvelope:
    def test_single_json_doc_stdout_no_json_stderr(self, tmp_path):
        result = run_cli("status", "--json", workspace_dir=tmp_path)
        parse_envelope(result)
        assert "{" not in result.stderr


class TestExitCodes:
    def test_status_uninitialized(self, tmp_path):
        result = run_cli("status", "--json", workspace_dir=tmp_path)
        assert result.returncode == 0
        env = parse_envelope(result)
        assert env["data"]["initialized"] is False
        assert env["data"]["legal_actions"] == ["init"]

    def test_init_creates_skeleton(self, tmp_path):
        result = run_cli("init", "--json", workspace_dir=tmp_path)
        assert result.returncode == 0
        env = parse_envelope(result)
        assert env["data"]["initialized"] is True
        assert (tmp_path / "novelos.yaml").is_file()
        assert (tmp_path / ".novelos" / "events.jsonl").is_file()
        assert (tmp_path / "story" / "chapters").is_dir()

    def test_reinit_exit_2_illegal_operation(self, tmp_path):
        assert run_cli("init", "--json", workspace_dir=tmp_path).returncode == 0
        result = run_cli("init", "--json", workspace_dir=tmp_path)
        assert result.returncode == 2
        env = parse_envelope(result)
        assert env["ok"] is False
        assert env["errors"][0]["code"] == "ILLEGAL_OPERATION"

    def test_unknown_subcommand_exit_4_usage_error(self, tmp_path):
        result = run_cli("bogus-verb", workspace_dir=tmp_path)
        assert result.returncode == 4
        env = parse_envelope(result)
        assert env["errors"][0]["code"] == "USAGE_ERROR"

    def test_corrupt_events_status_exit_5(self, tmp_path):
        assert run_cli("init", "--json", workspace_dir=tmp_path).returncode == 0
        (tmp_path / ".novelos" / "events.jsonl").write_bytes(b"not json\n")
        result = run_cli("status", "--json", workspace_dir=tmp_path)
        assert result.returncode == 5
        env = parse_envelope(result)
        assert env["errors"][0]["code"] == "WORKSPACE_CORRUPT"


class TestInitThenScan:
    """r5 锚定断言（冻结文档 10 §2/§6）：变更命令后立即 integrity-scan → PASS。"""

    def test_init_then_scan_passes(self, tmp_path):
        assert run_cli("init", "--json", workspace_dir=tmp_path).returncode == 0
        result = run_cli("integrity-scan", "--json", workspace_dir=tmp_path)
        assert result.returncode == 0
        env = parse_envelope(result)
        assert env["ok"] is True
        assert env["data"]["scanned_files"] == 1
        assert env["data"]["blocking_mismatches"] == []
        assert env["data"]["derived_dirty"] == []
        assert env["data"]["chain_ok"] is True
        assert env["data"]["anchor_ok"] is True


class TestTamperScan:
    def test_byte_flip_novelos_yaml_exit_2(self, tmp_path):
        assert run_cli("init", "--json", workspace_dir=tmp_path).returncode == 0
        managed = tmp_path / "novelos.yaml"
        raw = managed.read_bytes()
        managed.write_bytes(raw + b"# out-of-band\n")

        result = run_cli("integrity-scan", "--json", workspace_dir=tmp_path)
        assert result.returncode == 2
        env = parse_envelope(result)
        assert env["ok"] is False
        assert env["errors"][0]["code"] == "OUT_OF_BAND_WRITE_DETECTED"
        (entry,) = env["data"]["blocking_mismatches"]
        assert entry["path"] == "novelos.yaml"
        assert entry["expected_hash"].startswith("sha256:")
        assert entry["last_legitimate_event"] == "ev-000001"

    def test_chain_corruption_exit_5(self, tmp_path):
        assert run_cli("init", "--json", workspace_dir=tmp_path).returncode == 0
        events_path = tmp_path / ".novelos" / "events.jsonl"
        events_path.write_bytes(b'{"broken": true}\n')
        result = run_cli("integrity-scan", "--json", workspace_dir=tmp_path)
        assert result.returncode == 5
        env = parse_envelope(result)
        assert env["errors"][0]["code"] == "WORKSPACE_CORRUPT"


class TestDoctor:
    def test_empty_pi_agent_dir_exit_5(self, tmp_path):
        pi_dir = tmp_path / "pi-agent"
        pi_dir.mkdir()
        result = run_cli("doctor", "--json", env_extra={"PI_AGENT_DIR": str(pi_dir)})
        assert result.returncode == 5
        env = parse_envelope(result)
        assert env["data"]["all_ok"] is False
        checks = {c["id"]: c for c in env["data"]["checks"]}
        assert checks["skill_placement"]["ok"] is False
        assert "install.py" in checks["skill_placement"]["hint"]
        assert checks["extension_placement"]["ok"] is False

    def test_assets_placed_exit_0(self, tmp_path):
        pi_dir = tmp_path / "pi-agent"
        (pi_dir / "skills" / "novelos").mkdir(parents=True)
        (pi_dir / "skills" / "novelos" / "SKILL.md").write_text("# skill", encoding="utf-8")
        (pi_dir / "extensions" / "novelos").mkdir(parents=True)
        (pi_dir / "extensions" / "novelos" / "index.ts").write_text("export default {}", encoding="utf-8")
        result = run_cli("doctor", "--json", env_extra={"PI_AGENT_DIR": str(pi_dir)})
        assert result.returncode == 0
        env = parse_envelope(result)
        assert env["data"]["all_ok"] is True


class TestRequestId:
    def test_replay_same_response_single_event(self, tmp_path):
        request_id = str(uuid.uuid4())
        first = run_cli("init", "--json", "--request-id", request_id, workspace_dir=tmp_path)
        assert first.returncode == 0
        second = run_cli("init", "--json", "--request-id", request_id, workspace_dir=tmp_path)
        assert second.returncode == 0
        assert parse_envelope(first)["data"] == parse_envelope(second)["data"]
        events_bytes = (tmp_path / ".novelos" / "events.jsonl").read_bytes()
        assert len(events_bytes.splitlines()) == 1

    def test_conflicting_args_exit_2(self, tmp_path):
        request_id = str(uuid.uuid4())
        assert run_cli(
            "init", "--json", "--request-id", request_id, "--project-name", "alpha", workspace_dir=tmp_path
        ).returncode == 0
        result = run_cli(
            "init", "--json", "--request-id", request_id, "--project-name", "beta", workspace_dir=tmp_path
        )
        assert result.returncode == 2
        env = parse_envelope(result)
        assert env["errors"][0]["code"] == "REQUEST_ID_CONFLICT"


class TestIntegrityScanUninitialized:
    def test_not_initialized_exit_2(self, tmp_path):
        result = run_cli("integrity-scan", "--json", workspace_dir=tmp_path)
        assert result.returncode == 2
        env = parse_envelope(result)
        assert env["errors"][0]["code"] == "NOT_INITIALIZED"


class TestNextStructured:
    def test_uninitialized(self, tmp_path):
        result = run_cli("next", "--json", workspace_dir=tmp_path)
        assert result.returncode == 0
        data = parse_envelope(result)["data"]
        assert data["suggested_action"] == "init"
        assert data["reason_code"] == "NOT_INITIALIZED"
        assert data["user_message"] == "还没有作品。要开始新故事吗？"

    def test_initialized_no_dev_jargon(self, tmp_path):
        assert run_cli("init", "--json", workspace_dir=tmp_path).returncode == 0
        result = run_cli("next", "--json", workspace_dir=tmp_path)
        assert result.returncode == 0
        data = parse_envelope(result)["data"]
        assert data["suggested_action"] is None
        assert data["reason_code"] == "NO_ACTION_IMPLEMENTED"
        assert data["user_message"] == "作品已初始化。当前版本尚未开放后续创作动作。"
        for value in (data["user_message"], data["reason"]):
            assert "Goal" not in value
            assert "Phase" not in value


class TestUtf8Output:
    """Windows 回归：stdout 必须是严格 UTF-8 字节（不随系统代码页 cp936）。"""

    def test_chinese_json_is_strict_utf8(self, tmp_path):
        cmd = [sys.executable, "-m", "novelos", "next", "--json", "--workspace", str(tmp_path)]
        proc = subprocess.run(cmd, capture_output=True)
        env = json.loads(proc.stdout.decode("utf-8"))  # 严格解码：cp936 字节会在此失败
        assert env["data"]["user_message"] == "还没有作品。要开始新故事吗？"
