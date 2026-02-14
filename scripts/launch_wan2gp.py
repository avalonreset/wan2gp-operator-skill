#!/usr/bin/env python3
"""
Launch Wan2GP UI from terminal with optional detached mode.

Usage:
  python scripts/launch_wan2gp.py --wan-root ./Wan2GP
  python scripts/launch_wan2gp.py --wan-root ./Wan2GP --foreground
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description="Launch Wan2GP UI")
    parser.add_argument("--wan-root", default="./Wan2GP", help="Wan2GP root path containing wgp.py")
    parser.add_argument("--env-manager", choices=["auto", "conda", "venv", "none"], default="auto")
    parser.add_argument("--env-name", default="wan2gp", help="Conda env name or venv folder name")
    parser.add_argument("--server-port", type=int, default=7860, help="Wan2GP web server port")
    parser.add_argument("--listen", action="store_true", help="Enable --listen for network access")
    parser.add_argument("--open-browser", action="store_true", help="Enable --open-browser")
    parser.add_argument("--foreground", action="store_true", help="Run in foreground")
    parser.add_argument("--log-file", help="Log file path for detached mode")
    return parser.parse_args()


def _resolve_env_manager(requested: str) -> str:
    """Resolve auto env manager."""
    if requested != "auto":
        return requested
    if shutil.which("conda"):
        return "conda"
    return "venv"


def _port_available(port: int) -> bool:
    """Check if TCP port is currently free on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _build_command(wan_root: Path, env_manager: str, env_name: str, port: int, listen: bool, open_browser: bool) -> list[str]:
    """Build launch command."""
    base = ["python", "wgp.py", "--server-port", str(port)]
    if listen:
        base.append("--listen")
    if open_browser:
        base.append("--open-browser")

    if env_manager == "conda":
        return ["conda", "run", "-n", env_name, *base]
    if env_manager == "venv":
        py = wan_root / env_name / "Scripts" / "python.exe"
        return [str(py), "wgp.py", "--server-port", str(port), *(["--listen"] if listen else []), *(["--open-browser"] if open_browser else [])]
    return base


def _default_log_file(wan_root: Path) -> Path:
    """Generate default detached log path."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    logs_dir = wan_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return (logs_dir / f"wan2gp-ui-{ts}.log").resolve()


def main() -> int:
    """CLI entrypoint."""
    args = _parse_args()
    wan_root = Path(args.wan_root).expanduser().resolve()
    if not (wan_root / "wgp.py").exists():
        print(json.dumps({"status": "error", "error": f"wgp.py not found in {wan_root}"}, indent=2), file=sys.stderr)
        return 1

    env_manager = _resolve_env_manager(args.env_manager)
    if env_manager == "venv":
        py = wan_root / args.env_name / "Scripts" / "python.exe"
        if not py.exists():
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": f"Venv python not found: {py}. Run setup first.",
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1

    if not _port_available(args.server_port):
        print(
            json.dumps(
                {"status": "error", "error": f"Port {args.server_port} is already in use."},
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    command = _build_command(
        wan_root=wan_root,
        env_manager=env_manager,
        env_name=args.env_name,
        port=args.server_port,
        listen=args.listen,
        open_browser=args.open_browser,
    )

    if args.foreground:
        process = subprocess.run(command, cwd=wan_root)
        return process.returncode

    log_file = Path(args.log_file).expanduser().resolve() if args.log_file else _default_log_file(wan_root)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_file, "w", encoding="utf-8")

    process = subprocess.Popen(
        command,
        cwd=wan_root,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )

    report: dict[str, Any] = {
        "status": "success",
        "mode": "detached",
        "pid": process.pid,
        "wan_root": str(wan_root),
        "env_manager": env_manager,
        "server_url": f"http://127.0.0.1:{args.server_port}",
        "log_file": str(log_file),
        "command": command,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
