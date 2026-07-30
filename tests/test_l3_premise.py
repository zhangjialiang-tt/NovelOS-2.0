"""L3: deterministic premise 链（evaluation fixture，无真实 Agent）。

链 1 happy：空目录 → init → status/next → task open → 缺一节 → submit(fixture) →
validate False → 补齐 rev2 → validate True → present → decide accept（免 nonce）→
落盘 → checkpoint → scan → status premise_accepted。落点标记：候选/提交事件
source_mode == DETERMINISTIC_FIXTURE（10 §3），决定来源 TEST_FIXTURE。

链 2 REVISE + resume：decide revise → 重启（新进程）→ task open 无 brief →
resumed + original_brief + revision_guidance_ref → rev2 → accept → scan PASS。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.l3

FIXTURES = Path(__file__).parent / "fixtures"
EVAL_ENV = {"NOVELOS_RUN_MODE": "evaluation"}
BRIEF = "记忆当铺：人们典当记忆换钱，主角是学徒"


def run_cli(*args, workspace_dir=None):
    cmd = [sys.executable, "-m", "novelos", *args]
    if workspace_dir is not None:
        cmd += ["--workspace", str(workspace_dir)]
    env = dict(os.environ)
    env.update(EVAL_ENV)
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", env=env)
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"one JSON doc per call; stdout={result.stdout!r} stderr={result.stderr!r}"
    env_json = json.loads(lines[0])
    assert set(env_json) == {"ok", "data", "errors"}
    return result.returncode, env_json


def read_events(ws: Path) -> list[dict]:
    return [
        json.loads(ln)
        for ln in (ws / ".novelos" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


def write_premise(ws: Path, fixture_name: str) -> None:
    staging = ws / "work" / "task-001"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "premise.md").write_bytes((FIXTURES / "premise" / fixture_name).read_bytes())


def submit_validate_present(ws: Path) -> dict:
    code, env = run_cli("candidate", "submit", "task-001", "--source-mode", "DETERMINISTIC_FIXTURE", "--json", workspace_dir=ws)
    assert code == 0, env
    code, env = run_cli("validate", "task-001", "--json", workspace_dir=ws)
    assert code == 0 and env["data"]["valid"] is True, env
    code, env = run_cli("present", "task-001", "--json", workspace_dir=ws)
    assert code == 0, env
    return env["data"]


def test_chain_happy_accept(tmp_path):
    ws = tmp_path / "novel"
    ws.mkdir()

    # 1. init
    code, env = run_cli("init", "--json", workspace_dir=ws)
    assert code == 0 and env["data"]["initialized"] is True

    # 2. status → legal_actions ["premise"]
    code, env = run_cli("status", "--json", workspace_dir=ws)
    assert code == 0 and env["data"]["legal_actions"] == ["premise"]

    # 3. next → open_task/premise
    code, env = run_cli("next", "--json", workspace_dir=ws)
    assert code == 0
    assert env["data"]["suggested_action"] == "open_task"
    assert env["data"]["task_type"] == "premise"

    # 4. task open
    code, env = run_cli("task", "open", "--task-type", "premise", "--brief", BRIEF, "--json", workspace_dir=ws)
    assert code == 0 and env["data"]["task_id"] == "task-001"

    # 5. 故意缺一节 → submit → validate False（断言缺失节名）
    write_premise(ws, "missing-section.md")
    code, env = run_cli("candidate", "submit", "task-001", "--source-mode", "DETERMINISTIC_FIXTURE", "--json", workspace_dir=ws)
    assert code == 0 and env["data"]["candidate_revision"] == 1
    code, env = run_cli("validate", "task-001", "--json", workspace_dir=ws)
    assert code == 0 and env["data"]["valid"] is False
    assert any("失败代价" in e["message"] for e in env["data"]["errors"]), env["data"]["errors"]

    # 6. 补齐 → rev2 → validate True
    write_premise(ws, "valid.md")
    code, env = run_cli("candidate", "submit", "task-001", "--source-mode", "DETERMINISTIC_FIXTURE", "--json", workspace_dir=ws)
    assert code == 0 and env["data"]["candidate_revision"] == 2
    code, env = run_cli("validate", "task-001", "--json", workspace_dir=ws)
    assert code == 0 and env["data"]["valid"] is True

    # 7. present
    code, env = run_cli("present", "task-001", "--json", workspace_dir=ws)
    assert code == 0
    assert env["data"]["pending_decision"]["candidate_revision"] == 2

    # 8. decide accept（fixture 免 nonce）
    code, env = run_cli(
        "decide", "task-001", "--revision", "2",
        "--fixture", str(FIXTURES / "decisions" / "accept-premise.json"),
        "--source", "TEST_FIXTURE", "--json",
        workspace_dir=ws,
    )
    assert code == 0, env
    assert env["data"]["task_status"] == "DONE"

    # 9. 落盘 == rev2 规范化字节
    story = ws / "story" / "premise.md"
    assert story.read_bytes() == (FIXTURES / "premise" / "valid.md").read_bytes()

    # 10. checkpoint + scan
    code, env = run_cli("checkpoint", "--json", workspace_dir=ws)
    assert code == 0 and env["data"]["accepted_artifact_refs"] == ["premise@1"]
    code, env = run_cli("integrity-scan", "--json", workspace_dir=ws)
    assert code == 0 and env["data"]["chain_ok"] is True and env["data"]["anchor_ok"] is True

    # 11. status → premise_accepted + completed 含「故事核心方向」
    code, env = run_cli("status", "--json", workspace_dir=ws)
    assert code == 0
    assert env["data"]["stage"] == "premise_accepted"
    assert "故事核心方向" in env["data"]["completed"]
    assert env["data"]["legal_actions"] == []

    # 12. 落点标记（10 §3）：候选与提交事件 source_mode 如实
    by_type = {}
    for ev in read_events(ws):
        by_type.setdefault(ev["type"], []).append(ev)
    submitted = by_type["CANDIDATE_SUBMITTED"]
    assert len(submitted) == 2
    assert all(ev["source_mode"] == "DETERMINISTIC_FIXTURE" for ev in submitted)
    (committed,) = by_type["COMMITTED"]
    assert committed["source_mode"] == "DETERMINISTIC_FIXTURE"
    assert committed["decision_ref"]["source"] == "TEST_FIXTURE"


def test_chain_revise_resume_accept(tmp_path):
    ws = tmp_path / "novel"
    ws.mkdir()
    run_cli("init", "--json", workspace_dir=ws)
    code, env = run_cli("task", "open", "--task-type", "premise", "--brief", "A", "--json", workspace_dir=ws)
    assert code == 0 and env["data"]["task_id"] == "task-001"

    write_premise(ws, "valid.md")
    submit_validate_present(ws)

    # REVISE（fixture）
    code, env = run_cli(
        "decide", "task-001", "--revision", "1",
        "--fixture", str(FIXTURES / "decisions" / "revise-premise.json"),
        "--source", "TEST_FIXTURE", "--json",
        workspace_dir=ws,
    )
    assert code == 0 and env["data"]["task_status"] == "OPEN", env

    # 模拟重启：新进程 CLI 调用；task open 不带 brief → resume
    code, env = run_cli("task", "open", "--task-type", "premise", "--json", workspace_dir=ws)
    assert code == 0, env
    data = env["data"]
    assert data["task_id"] == "task-001"
    assert data["resumed"] is True
    assert data["original_brief"] == "A"
    assert data["revision_guidance_ref"] == ".novelos/tasks/task-001/context/revision-notes/rev-001.md"

    # 意见文件存在且含 note
    note = ws / ".novelos" / "tasks" / "task-001" / "context" / "revision-notes" / "rev-001.md"
    assert note.is_file()
    assert "把失败代价写具体" in note.read_text(encoding="utf-8")

    # rev2 → accept
    write_premise(ws, "valid.md")
    submit_validate_present(ws)
    code, env = run_cli(
        "decide", "task-001", "--revision", "2",
        "--fixture", str(FIXTURES / "decisions" / "accept-premise.json"),
        "--source", "TEST_FIXTURE", "--json",
        workspace_dir=ws,
    )
    assert code == 0 and env["data"]["task_status"] == "DONE", env
    assert (ws / "story" / "premise.md").is_file()

    code, env = run_cli("integrity-scan", "--json", workspace_dir=ws)
    assert code == 0 and env["data"]["chain_ok"] is True and env["data"]["anchor_ok"] is True

    # REVISE 逐轮不可变：仅一轮意见文件
    notes_dir = ws / ".novelos" / "tasks" / "task-001" / "context" / "revision-notes"
    assert sorted(p.name for p in notes_dir.glob("rev-*.md")) == ["rev-001.md"]
