#!/usr/bin/env python3
"""
Generate or execute a Wan2GP setup plan.

Usage:
  python scripts/setup_wan2gp.py
  python scripts/setup_wan2gp.py --target-dir E:/tools/Wan2GP --execute
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from detect_gpu import build_report


def _pick_torch_install(gpu_report: dict[str, Any]) -> dict[str, str]:
    """Select a PyTorch install command based on detected hardware."""
    backend = gpu_report.get("backend", "unknown")
    gpus = gpu_report.get("gpus", [])
    names = " ".join(str(g.get("name", "")) for g in gpus).lower()

    if backend == "nvidia":
        if "rtx 50" in names:
            return {
                "reason": "RTX 50-series detected, using CUDA 13 wheel path.",
                "cmd": "pip install torch==2.10.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130",
            }
        if "gtx 10" in names:
            return {
                "reason": "GTX 10-series detected, using conservative CUDA 12.8 test wheels.",
                "cmd": "pip install torch==2.7.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/test/cu128",
            }
        return {
            "reason": "NVIDIA GPU detected, using CUDA 13 stable wheel path.",
            "cmd": "pip install torch==2.10.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130",
        }

    if backend == "amd":
        return {
            "reason": "ROCm/AMD environment detected; using default pip resolver for torch stack.",
            "cmd": "pip install torch torchvision torchaudio",
        }

    return {
        "reason": "No GPU runtime detected; keeping torch install generic.",
        "cmd": "pip install torch torchvision torchaudio",
    }


def _resolve_env_manager(env_manager: str) -> str:
    """Resolve auto env manager choice."""
    if env_manager != "auto":
        return env_manager
    if shutil.which("conda"):
        return "conda"
    return "venv"


def _parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description="Plan or execute Wan2GP setup")
    parser.add_argument("--target-dir", default="./Wan2GP", help="Destination directory for Wan2GP repo")
    parser.add_argument("--repo", default="https://github.com/deepbeepmeep/Wan2GP.git", help="Wan2GP git URL")
    parser.add_argument("--branch", default="main", help="Git branch to use")
    parser.add_argument("--env-manager", choices=["auto", "conda", "venv", "none"], default="auto")
    parser.add_argument("--env-name", default="wan2gp", help="Conda env name or venv folder name")
    parser.add_argument("--python-version", default="3.11.14", help="Python version for conda env creation")
    parser.add_argument("--execute", action="store_true", help="Execute setup commands")
    return parser.parse_args()


def _build_plan(
    target: Path,
    env_manager: str,
    env_name: str,
    python_version: str,
    repo: str,
    branch: str,
    torch_info: dict[str, str],
) -> list[dict[str, str]]:
    """Build command sequence for setup."""
    clone_or_pull_cmd = (
        f'git clone --branch {branch} "{repo}" "{target}"'
        if not target.exists()
        else f'git -C "{target}" pull --ff-only'
    )

    plan: list[dict[str, str]] = [{"step": "clone_or_update_repo", "cmd": clone_or_pull_cmd}]

    if env_manager == "conda":
        plan.extend(
            [
                {
                    "step": "ensure_conda_env",
                    "cmd": (
                        f"conda run -n {env_name} python --version "
                        f"|| conda create -y -n {env_name} python={python_version}"
                    ),
                },
                {
                    "step": "install_torch",
                    "cmd": f'conda run -n {env_name} {torch_info["cmd"]}',
                },
                {
                    "step": "install_requirements",
                    "cmd": f"conda run -n {env_name} pip install -r requirements.txt",
                    "cwd": str(target),
                },
                {
                    "step": "verify",
                    "cmd": (
                        f"conda run -n {env_name} python wgp.py "
                        f"--process defaults\\t2v_1.3B.json --dry-run"
                    ),
                    "cwd": str(target),
                },
            ]
        )
    elif env_manager == "venv":
        venv_dir = target / env_name
        python_exe = venv_dir / "Scripts" / "python.exe"
        pip_torch_cmd = torch_info["cmd"].replace("pip ", f'"{python_exe}" -m pip ', 1)
        plan.extend(
            [
                {
                    "step": "ensure_venv",
                    "cmd": (
                        f'if not exist "{python_exe}" (python -m venv "{venv_dir}")'
                    ),
                },
                {
                    "step": "install_torch",
                    "cmd": f'"{python_exe}" -m pip install --upgrade pip && {pip_torch_cmd}',
                },
                {
                    "step": "install_requirements",
                    "cmd": f'"{python_exe}" -m pip install -r requirements.txt',
                    "cwd": str(target),
                },
                {
                    "step": "verify",
                    "cmd": (
                        f'"{python_exe}" wgp.py '
                        f'--process defaults\\t2v_1.3B.json --dry-run'
                    ),
                    "cwd": str(target),
                },
            ]
        )
    else:
        plan.extend(
            [
                {"step": "install_torch", "cmd": torch_info["cmd"]},
                {"step": "install_requirements", "cmd": "pip install -r requirements.txt", "cwd": str(target)},
                {
                    "step": "verify",
                    "cmd": "python wgp.py --process defaults\\t2v_1.3B.json --dry-run",
                    "cwd": str(target),
                },
            ]
        )
    return plan


def _run_step(command: str, cwd: str | None = None) -> dict[str, Any]:
    """Execute one shell command step."""
    process = subprocess.run(command, shell=True, text=True, capture_output=True, cwd=cwd)
    return {
        "returncode": process.returncode,
        "stdout_tail": process.stdout[-1600:],
        "stderr_tail": process.stderr[-1600:],
    }


def main() -> int:
    """CLI entrypoint."""
    args = _parse_args()
    target = Path(args.target_dir).expanduser().resolve()
    resolved_env_manager = _resolve_env_manager(args.env_manager)

    gpu_report = build_report()
    torch_info = _pick_torch_install(gpu_report)
    plan = _build_plan(
        target=target,
        env_manager=resolved_env_manager,
        env_name=args.env_name,
        python_version=args.python_version,
        repo=args.repo,
        branch=args.branch,
        torch_info=torch_info,
    )

    report: dict[str, Any] = {
        "status": "planned",
        "target_dir": str(target),
        "env_manager_requested": args.env_manager,
        "env_manager_resolved": resolved_env_manager,
        "env_name": args.env_name,
        "torch_selection": torch_info,
        "steps": plan,
        "executed": False,
    }

    if not args.execute:
        print(json.dumps(report, indent=2))
        return 0

    results: list[dict[str, Any]] = []
    for step in plan:
        result = _run_step(step["cmd"], cwd=step.get("cwd"))
        results.append({"step": step["step"], **result})
        if result["returncode"] != 0:
            report.update({"status": "error", "executed": True, "results": results})
            print(json.dumps(report, indent=2))
            return 1

    report.update({"status": "success", "executed": True, "results": results})
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
