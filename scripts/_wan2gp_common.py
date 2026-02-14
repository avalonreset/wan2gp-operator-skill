#!/usr/bin/env python3
"""
Shared helpers for Wan2GP operator scripts.
"""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_QUEUE_EXTENSIONS = {".zip", ".json"}
MODEL_PRESETS = {
    "none": "",
    "t2v-1-3B": "--t2v-1-3B",
    "t2v-14B": "--t2v-14B",
    "i2v-1-3B": "--i2v-1-3B",
    "i2v-14B": "--i2v-14B",
    "vace-1-3B": "--vace-1-3B",
    "vace-1.3B": "--vace-1-3B",
}
ATTENTION_MODES = {"sdpa", "flash", "sage", "sage2"}
OPERATOR_STATE_FILENAME = ".wan2gp_operator_state.json"


def resolve_wan_root(path_str: str) -> Path:
    """Resolve and validate Wan2GP root folder."""
    root = Path(path_str).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Wan2GP root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Wan2GP root is not a directory: {root}")
    if not (root / "wgp.py").exists():
        raise FileNotFoundError(f"wgp.py not found in Wan2GP root: {root}")
    return root


def resolve_process_file(path_str: str, wan_root: Path) -> Path:
    """Resolve queue/settings file path, allowing paths relative to Wan2GP root."""
    user_path = Path(path_str).expanduser()
    if user_path.exists():
        process_file = user_path.resolve()
    else:
        candidate = (wan_root / user_path).resolve()
        process_file = candidate

    if not process_file.exists():
        raise FileNotFoundError(f"Queue/settings file not found: {process_file}")
    if process_file.suffix.lower() not in SUPPORTED_QUEUE_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {process_file.suffix}. "
            f"Use one of: {', '.join(sorted(SUPPORTED_QUEUE_EXTENSIONS))}"
        )
    return process_file


def resolve_optional_path(path_str: str | None, base_dir: Path) -> Path | None:
    """Resolve optional path; relative values are anchored to base_dir."""
    if not path_str:
        return None
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def resolve_python_executable(requested: str, wan_root: Path) -> str:
    """Resolve Python executable, preferring Wan2GP local venv when available."""
    if requested and requested != "auto":
        return requested

    candidates = [
        wan_root / "wan2gp" / "Scripts" / "python.exe",
        wan_root / "wan2gp" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return "python"


def operator_state_path(wan_root: Path) -> Path:
    """State file path for learned compatibility information."""
    return wan_root / OPERATOR_STATE_FILENAME


def load_operator_state(wan_root: Path) -> dict[str, Any]:
    """Load persisted operator state, returning defaults when missing."""
    path = operator_state_path(wan_root)
    base: dict[str, Any] = {
        "version": 1,
        "updated_at": _utc_now_iso(),
        "unsupported_args": {},
        "unsupported_attention_modes": {},
        "incidents": [],
    }
    if not path.exists():
        return base
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return base
    if not isinstance(loaded, dict):
        return base
    for key, default_value in base.items():
        loaded.setdefault(key, default_value)
    return loaded


def save_operator_state(wan_root: Path, state: dict[str, Any]) -> Path:
    """Persist operator state to Wan2GP root."""
    state["updated_at"] = _utc_now_iso()
    path = operator_state_path(wan_root)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return path


def is_flag_known_unsupported(state: dict[str, Any], flag: str) -> bool:
    """Check whether a CLI flag is marked unsupported."""
    unsupported = state.get("unsupported_args", {})
    return isinstance(unsupported, dict) and flag in unsupported


def mark_unsupported_arg(state: dict[str, Any], flag: str, evidence: str = "") -> None:
    """Record an unsupported CLI flag learned from runtime errors."""
    unsupported = state.setdefault("unsupported_args", {})
    if not isinstance(unsupported, dict):
        unsupported = {}
        state["unsupported_args"] = unsupported

    now = _utc_now_iso()
    existing = unsupported.get(flag, {})
    if not isinstance(existing, dict):
        existing = {}

    count = int(existing.get("count", 0)) + 1
    unsupported[flag] = {
        "first_seen": existing.get("first_seen", now),
        "last_seen": now,
        "count": count,
        "evidence": evidence[:400],
    }


def is_attention_known_unsupported(state: dict[str, Any], mode: str) -> bool:
    """Check whether an attention mode is marked unsupported."""
    unsupported = state.get("unsupported_attention_modes", {})
    return isinstance(unsupported, dict) and mode in unsupported


def mark_unsupported_attention(state: dict[str, Any], mode: str, evidence: str = "") -> None:
    """Record an unsupported attention mode learned from runtime logs."""
    unsupported = state.setdefault("unsupported_attention_modes", {})
    if not isinstance(unsupported, dict):
        unsupported = {}
        state["unsupported_attention_modes"] = unsupported

    now = _utc_now_iso()
    existing = unsupported.get(mode, {})
    if not isinstance(existing, dict):
        existing = {}

    count = int(existing.get("count", 0)) + 1
    unsupported[mode] = {
        "first_seen": existing.get("first_seen", now),
        "last_seen": now,
        "count": count,
        "evidence": evidence[:400],
    }


def append_incident(state: dict[str, Any], signature: str, details: dict[str, Any]) -> None:
    """Append a bounded incident history entry."""
    incidents = state.setdefault("incidents", [])
    if not isinstance(incidents, list):
        incidents = []
        state["incidents"] = incidents
    incidents.append(
        {
            "timestamp": _utc_now_iso(),
            "signature": signature,
            "details": details,
        }
    )
    max_incidents = 100
    if len(incidents) > max_incidents:
        del incidents[:-max_incidents]


def strip_flag_with_value(command: list[str], flag: str) -> list[str]:
    """Return a command with a '--flag value' pair removed if present."""
    if flag not in command:
        return command[:]
    cleaned: list[str] = []
    skip_next = False
    for idx, token in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        if token == flag:
            has_value = idx + 1 < len(command) and not command[idx + 1].startswith("--")
            skip_next = has_value
            continue
        cleaned.append(token)
    return cleaned


def _utc_now_iso() -> str:
    """UTC timestamp helper."""
    return datetime.now(timezone.utc).isoformat()


def build_wan2gp_command(
    python_exe: str,
    process_file: Path,
    output_dir: Path | None = None,
    attention: str | None = None,
    profile: str | None = None,
    verbose: int = 1,
    dry_run: bool = False,
    compile_enabled: bool = False,
    fp16: bool = False,
    teacache: float | None = None,
    model_preset: str = "none",
    extra_args: list[str] | None = None,
) -> list[str]:
    """Build a safe Wan2GP CLI command list."""
    command = [python_exe, "wgp.py", "--process", str(process_file)]

    if output_dir:
        command.extend(["--output-dir", str(output_dir)])
    if dry_run:
        command.append("--dry-run")

    command.extend(["--verbose", str(verbose)])

    if attention:
        if attention not in ATTENTION_MODES:
            raise ValueError(f"Unsupported attention mode: {attention}")
        command.extend(["--attention", attention])
    if profile:
        command.extend(["--profile", str(profile)])
    if teacache is not None:
        command.extend(["--teacache", str(teacache)])
    if compile_enabled:
        command.append("--compile")
    if fp16:
        command.append("--fp16")
    if model_preset not in MODEL_PRESETS:
        raise ValueError(
            f"Unsupported model preset: {model_preset}. "
            f"Supported: {', '.join(sorted(MODEL_PRESETS.keys()))}"
        )
    model_flag = MODEL_PRESETS[model_preset]
    if model_flag:
        command.append(model_flag)

    if extra_args:
        command.extend(extra_args)
    return command


def command_to_string(command: list[str]) -> str:
    """Render a command list in a shell-friendly form."""
    if platform.system().lower().startswith("win"):
        return subprocess.list2cmdline(command)
    return " ".join(_shell_quote(part) for part in command)


def _shell_quote(value: str) -> str:
    """Minimal POSIX-safe quoting for display."""
    if not value:
        return "''"
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/:=")
    if all(ch in safe_chars for ch in value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"
