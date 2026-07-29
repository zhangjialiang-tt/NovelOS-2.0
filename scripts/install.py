#!/usr/bin/env python3
"""NovelOS 本地安装脚本（Phase 1，stdlib-only）。

安装两半（冻结文档 02 §4.1）：
  1. Python Core：~/.novelos/venv 内可编辑安装 + ~/.novelos/launcher.json（argv 记录）
  2. Pi 资产：~/.pi/agent/skills/novelos → pi/skill；~/.pi/agent/extensions/novelos → pi/extension
     （Windows 用目录联接 mklink /J，免管理员；posix 用 symlink；失败退化为复制）

自检实现冻结文档 02 §4.2 的"安装自检"诊断层：launcher version --json + doctor --json。

环境覆盖（L1 测试承载）：
  NOVELOS_INSTALL_ROOT  默认 ~/.novelos
  PI_AGENT_DIR          默认 ~/.pi/agent
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def install_root() -> Path:
    return Path(os.environ.get("NOVELOS_INSTALL_ROOT") or (Path.home() / ".novelos"))


def pi_agent_dir() -> Path:
    return Path(os.environ.get("PI_AGENT_DIR") or (Path.home() / ".pi" / "agent"))


def venv_python(root: Path) -> Path:
    if sys.platform == "win32":
        return root / "venv" / "Scripts" / "python.exe"
    return root / "venv" / "bin" / "python"


def run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    if env:
        merged.update(env)
    # errors="replace"：Windows 下 cmd/mklink 输出为 GBK，避免 UTF-8 解码崩溃
    return subprocess.run(cmd, capture_output=True, text=True, env=merged, errors="replace")


def ensure_venv(root: Path) -> Path:
    venv_py = venv_python(root)
    if venv_py.exists():
        return venv_py
    root.mkdir(parents=True, exist_ok=True)
    if shutil.which("uv"):
        proc = run(["uv", "venv", str(root / "venv")])
    else:
        proc = run([sys.executable, "-m", "venv", str(root / "venv")])
    if proc.returncode != 0 or not venv_py.exists():
        raise RuntimeError(f"创建虚拟环境失败：{proc.stderr.strip() or proc.stdout.strip()}")
    return venv_py


def install_core(venv_py: Path) -> None:
    if shutil.which("uv"):
        proc = run(["uv", "pip", "install", "--python", str(venv_py), "-e", str(REPO_ROOT)])
    else:
        proc = run([str(venv_py), "-m", "pip", "install", "-e", str(REPO_ROOT)])
    if proc.returncode != 0:
        raise RuntimeError(f"安装 Python Core 失败：{proc.stderr.strip() or proc.stdout.strip()}")


def query_version(venv_py: Path) -> dict:
    proc = run([str(venv_py), "-m", "novelos", "version", "--json"])
    if proc.returncode != 0:
        raise RuntimeError(f"Core version 查询失败（退出码 {proc.returncode}）：{proc.stderr.strip()}")
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    if not envelope.get("ok"):
        raise RuntimeError(f"Core version 返回错误信封：{envelope.get('errors')}")
    return envelope["data"]


def write_launcher(root: Path, venv_py: Path, version_data: dict) -> Path:
    launcher = root / "launcher.json"
    payload = {
        "argv": [str(venv_py), "-m", "novelos"],
        "core_version": version_data.get("core_version"),
        "protocol_version": version_data.get("protocol_version"),
        "repo_path": str(REPO_ROOT),
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    launcher.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return launcher


def _is_reparse_point(path: Path) -> bool:
    if sys.platform != "win32":
        return path.is_symlink()
    try:
        # lstat：不跟随联接，st_file_attributes 才反映 reparse point
        return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (AttributeError, OSError):
        return False


def link_dir(src: Path, dst: Path) -> str:
    """把 src 链接到 dst。返回落地方式：symlink / junction / copy / reused。"""
    dst.parent.mkdir(parents=True, exist_ok=True)

    if _is_reparse_point(dst):
        # 既有链接：目标相同则复用，不同则移除重建
        try:
            if os.path.realpath(dst) == os.path.realpath(src):
                return "reused"
        except OSError:
            pass
        if sys.platform == "win32":
            os.rmdir(dst)  # 联接以目录方式移除，不触及源
        else:
            dst.unlink()
    elif dst.exists():
        raise RuntimeError(
            f"{dst} 已存在且不是本安装脚本创建的链接；请人工确认后删除，再重新运行安装。"
        )

    if sys.platform == "win32":
        proc = run(["cmd", "/c", "mklink", "/J", str(dst), str(src)])
        if proc.returncode == 0 and dst.exists():
            return "junction"
        # 联接失败（少见文件系统限制）→ 复制兜底
        shutil.copytree(src, dst)
        return "copy"

    os.symlink(src, dst, target_is_directory=True)
    return "symlink"


def self_check(root: Path, pi_dir: Path) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    launcher = root / "launcher.json"
    if not launcher.is_file():
        results.append(("launcher.json", False, f"缺失：{launcher}（先运行 python scripts/install.py）"))
        results.append(("core version", False, "跳过（无 launcher）"))
        results.append(("doctor", False, "跳过（无 launcher）"))
        return results

    argv = json.loads(launcher.read_text(encoding="utf-8"))["argv"]

    proc = run([*argv, "version", "--json"])
    version_ok = False
    detail = f"退出码 {proc.returncode}"
    if proc.returncode == 0:
        try:
            envelope = json.loads(proc.stdout.strip().splitlines()[-1])
            protocol = str(envelope.get("data", {}).get("protocol_version", ""))
            version_ok = envelope.get("ok") is True and protocol.split(".")[0] == "1"
            detail = f"core {envelope.get('data', {}).get('core_version')} / protocol {protocol}"
        except (json.JSONDecodeError, IndexError):
            detail = "输出不是 JSON 信封"
    results.append(("core version", version_ok, detail))

    proc = run([*argv, "doctor", "--json"], env={"PI_AGENT_DIR": str(pi_dir)})
    doctor_ok = False
    detail = f"退出码 {proc.returncode}"
    if proc.returncode == 0:
        try:
            envelope = json.loads(proc.stdout.strip().splitlines()[-1])
            doctor_ok = envelope.get("data", {}).get("all_ok") is True
            if not doctor_ok:
                failed = [
                    c["id"]
                    for c in envelope.get("data", {}).get("checks", [])
                    if not c.get("ok")
                ]
                detail = f"未通过检查：{', '.join(failed)}（运行 python scripts/install.py）"
            else:
                detail = "all_ok"
        except (json.JSONDecodeError, IndexError):
            detail = "输出不是 JSON 信封"
    results.append(("doctor", doctor_ok, detail))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NovelOS 本地安装脚本")
    parser.add_argument("--check", action="store_true", help="仅运行自检，不安装")
    args = parser.parse_args(argv)

    root = install_root()
    pi_dir = pi_agent_dir()

    if not args.check:
        try:
            print(f"[1/4] 虚拟环境：{root / 'venv'}")
            venv_py = ensure_venv(root)
            print(f"[2/4] 安装 Python Core（editable）：{REPO_ROOT}")
            install_core(venv_py)
            version_data = query_version(venv_py)
            launcher = write_launcher(root, venv_py, version_data)
            print(f"      launcher.json 已写入：{launcher}")
            print(f"      core {version_data.get('core_version')} / protocol {version_data.get('protocol_version')}")
            print(f"[3/4] 链接 Pi 资产：{pi_dir}")
            skill_how = link_dir(REPO_ROOT / "pi" / "skill", pi_dir / "skills" / "novelos")
            ext_how = link_dir(REPO_ROOT / "pi" / "extension", pi_dir / "extensions" / "novelos")
            print(f"      skills/novelos（{skill_how}）、extensions/novelos（{ext_how}）")
            if "copy" in (skill_how, ext_how):
                print("      注意：复制落点不会随仓库编辑热更新（/reload 看不到改动）。")
        except RuntimeError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 2

    print(f"[4/4] 自检（PI_AGENT_DIR={pi_dir}）")
    checks = self_check(root, pi_dir)
    all_ok = True
    for name, ok, detail in checks:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}: {detail}")
        all_ok = all_ok and ok
    print("PASS" if all_ok else "FAIL")
    return 0 if all_ok else 2


if __name__ == "__main__":
    sys.exit(main())
