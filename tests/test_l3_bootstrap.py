"""L3: deterministic bootstrap chain — empty dir → init → board → scan → doctor."""

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.l3


def run_cli(*args, workspace_dir=None, env_extra=None):
    cmd = [sys.executable, "-m", "novelos", *args]
    if workspace_dir is not None:
        cmd += ["--workspace", str(workspace_dir)]
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"one JSON doc per call; got {result.stdout!r} / stderr {result.stderr!r}"
    env_json = json.loads(lines[0])
    assert set(env_json) == {"ok", "data", "errors"}  # 冻结文档 04 §1.3 信封形状
    return result.returncode, env_json


def test_bootstrap_vertical_slice(tmp_path):
    novel = tmp_path / "my-novel"
    novel.mkdir()
    pi_dir = tmp_path / "pi-agent"
    (pi_dir / "skills" / "novelos").mkdir(parents=True)
    (pi_dir / "skills" / "novelos" / "SKILL.md").write_text("# skill", encoding="utf-8")
    (pi_dir / "extensions" / "novelos").mkdir(parents=True)
    (pi_dir / "extensions" / "novelos" / "index.ts").write_text("export default {}", encoding="utf-8")

    # 1. version — 环境无关
    code, env = run_cli("version", "--json", workspace_dir=novel)
    assert code == 0 and env["ok"] is True
    assert env["data"]["protocol_version"] == "1.0"

    # 2. status 未初始化
    code, env = run_cli("status", "--json", workspace_dir=novel)
    assert code == 0 and env["ok"] is True
    assert env["data"]["initialized"] is False
    assert env["data"]["legal_actions"] == ["init"]

    # 3. next 未初始化 → 建议 init
    code, env = run_cli("next", "--json", workspace_dir=novel)
    assert code == 0 and env["ok"] is True
    assert env["data"]["suggested_action"] == "init"

    # 4. init
    code, env = run_cli("init", "--json", workspace_dir=novel)
    assert code == 0 and env["ok"] is True
    assert env["data"]["initialized"] is True

    # 5. status 已初始化
    code, env = run_cli("status", "--json", workspace_dir=novel)
    assert code == 0 and env["ok"] is True
    assert env["data"]["initialized"] is True
    assert env["data"]["project"] == "my-novel"
    assert env["data"]["stage"] == "initialized"
    assert env["data"]["completed"] == []
    assert env["data"]["issues"] == []

    # 6. next 已初始化 → none（Phase 1 运行时基础）
    code, env = run_cli("next", "--json", workspace_dir=novel)
    assert code == 0 and env["ok"] is True
    assert env["data"]["suggested_action"] == "none"

    # 7. integrity-scan 紧随变更命令 → PASS（r5 锚定）
    code, env = run_cli("integrity-scan", "--json", workspace_dir=novel)
    assert code == 0 and env["ok"] is True
    assert env["data"]["scanned_files"] == 1

    # 8. doctor（Pi 资产就位）
    code, env = run_cli("doctor", "--json", env_extra={"PI_AGENT_DIR": str(pi_dir)})
    assert code == 0 and env["ok"] is True
    assert env["data"]["all_ok"] is True

    # 9. 再次 integrity-scan — 只读命令不破坏锚定
    code, env = run_cli("integrity-scan", "--json", workspace_dir=novel)
    assert code == 0 and env["ok"] is True
    assert env["data"]["chain_ok"] is True
    assert env["data"]["anchor_ok"] is True
