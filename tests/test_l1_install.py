"""L1: installer + three-layer diagnostics (install layer, frozen doc 02 §4.2).

Module fixture runs scripts/install.py once against a tmp NOVELOS_INSTALL_ROOT /
PI_AGENT_DIR (via env override). Slow (~venv creation) but honest.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.l1

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "install.py"


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    base = tmp_path_factory.mktemp("novelos-install")
    install_root = base / "novelos-home"
    pi_dir = base / "pi-agent"
    env = dict(
        os.environ,
        NOVELOS_INSTALL_ROOT=str(install_root),
        PI_AGENT_DIR=str(pi_dir),
    )
    proc = subprocess.run(
        [sys.executable, str(INSTALLER)],
        capture_output=True,
        text=True,
        env=env,
    )
    return SimpleNamespace(
        proc=proc,
        install_root=install_root,
        pi_dir=pi_dir,
        output=proc.stdout + proc.stderr,
    )


def test_fresh_install_passes_and_launcher_works(installed):
    assert installed.proc.returncode == 0, installed.output
    assert "PASS" in installed.proc.stdout

    launcher = installed.install_root / "launcher.json"
    assert launcher.is_file()
    payload = json.loads(launcher.read_text(encoding="utf-8"))
    assert payload["argv"][1:] == ["-m", "novelos"]
    assert payload["protocol_version"] == "1.0"
    assert Path(payload["argv"][0]).exists()

    # launcher argv actually runs Core
    proc = subprocess.run(
        [*payload["argv"], "version", "--json"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    assert envelope["ok"] is True

    # Pi assets resolved through the link (junction on Windows, symlink elsewhere)
    assert (installed.pi_dir / "skills" / "novelos" / "SKILL.md").is_file()
    assert (installed.pi_dir / "extensions" / "novelos" / "index.ts").is_file()


def test_install_check_flag_repasses(installed):
    env = dict(
        os.environ,
        NOVELOS_INSTALL_ROOT=str(installed.install_root),
        PI_AGENT_DIR=str(installed.pi_dir),
    )
    proc = subprocess.run(
        [sys.executable, str(INSTALLER), "--check"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout


def test_doctor_empty_pi_dir_exit_5(tmp_path):
    empty_pi = tmp_path / "empty-pi"
    empty_pi.mkdir()
    proc = subprocess.run(
        [sys.executable, "-m", "novelos", "doctor", "--json"],
        capture_output=True,
        text=True,
        env=dict(os.environ, PI_AGENT_DIR=str(empty_pi)),
    )
    assert proc.returncode == 5
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    checks = {c["id"]: c for c in envelope["data"]["checks"]}
    assert checks["skill_placement"]["ok"] is False
    assert "install.py" in checks["skill_placement"]["hint"]


def test_doctor_fake_assets_exit_0(tmp_path):
    pi_dir = tmp_path / "fake-pi"
    (pi_dir / "skills" / "novelos").mkdir(parents=True)
    (pi_dir / "skills" / "novelos" / "SKILL.md").write_text("# skill", encoding="utf-8")
    (pi_dir / "extensions" / "novelos").mkdir(parents=True)
    (pi_dir / "extensions" / "novelos" / "index.ts").write_text("export default {}", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "novelos", "doctor", "--json"],
        capture_output=True,
        text=True,
        env=dict(os.environ, PI_AGENT_DIR=str(pi_dir)),
    )
    assert proc.returncode == 0
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    assert envelope["data"]["all_ok"] is True
