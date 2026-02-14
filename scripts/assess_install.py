#!/usr/bin/env python3
"""
Assess whether a machine is suitable for Wan2GP and provide install guidance.

Usage:
  python scripts/assess_install.py
"""

from __future__ import annotations

import json
import os
import platform
import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from detect_gpu import build_report


@dataclass
class SystemInfo:
    """Basic system information for readiness checks."""

    total_ram_gb: float
    free_disk_gb: float
    os_name: str
    python_version: str


def _get_total_ram_gb() -> float:
    """Get total system RAM in GB without third-party dependencies."""
    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            memory_status = MEMORYSTATUSEX()
            memory_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory_status))
            return round(memory_status.ullTotalPhys / (1024 ** 3), 1)
        except Exception:
            return 0.0

    # POSIX fallback
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return round((pages * page_size) / (1024 ** 3), 1)
    except Exception:
        return 0.0


def _get_free_disk_gb(path: Path) -> float:
    """Get free disk space for the filesystem containing path."""
    usage = shutil.disk_usage(path)
    return round(usage.free / (1024 ** 3), 1)


def _collect_system_info() -> SystemInfo:
    """Collect host system details."""
    return SystemInfo(
        total_ram_gb=_get_total_ram_gb(),
        free_disk_gb=_get_free_disk_gb(Path.cwd()),
        os_name=f"{platform.system()} {platform.release()}",
        python_version=platform.python_version(),
    )


def _build_recommendation(gpu_report: dict[str, Any], system_info: SystemInfo) -> dict[str, Any]:
    """Build suitability verdict and constraints."""
    backend = gpu_report.get("backend", "unknown")
    gpus = gpu_report.get("gpus", [])
    max_vram_gb = max((gpu.get("vram_gb", 0) for gpu in gpus), default=0.0)

    blockers: list[str] = []
    warnings: list[str] = []

    if backend == "unknown":
        blockers.append("No supported GPU runtime detected (nvidia-smi/rocm-smi not found).")
    if max_vram_gb > 0 and max_vram_gb < 6:
        blockers.append(f"Detected VRAM ({max_vram_gb}GB) is below Wan2GP practical minimum (~6GB).")
    if system_info.total_ram_gb > 0 and system_info.total_ram_gb < 16:
        blockers.append(f"System RAM ({system_info.total_ram_gb}GB) is below recommended minimum (16GB).")
    if system_info.free_disk_gb < 80:
        blockers.append(f"Free disk ({system_info.free_disk_gb}GB) is too low for model downloads and outputs.")

    if not blockers:
        if max_vram_gb >= 12 and system_info.total_ram_gb >= 32 and system_info.free_disk_gb >= 150:
            verdict = "recommended"
        else:
            verdict = "possible_with_constraints"
            warnings.append("Use smaller models/presets first and keep frame counts conservative.")
    else:
        verdict = "not_recommended"

    if system_info.python_version < "3.10":
        warnings.append("Python runtime appears old; Wan2GP expects modern Python environments.")

    model_advice: list[str] = []
    if max_vram_gb <= 8:
        model_advice.append("Start with t2v-1-3B and profile 4.")
    elif max_vram_gb <= 12:
        model_advice.append("Use t2v-14B with profile 4; drop to 1.3B if unstable.")
    else:
        model_advice.append("Use t2v-14B; consider Sage/Sage2 once dependencies are stable.")

    return {
        "verdict": verdict,
        "max_vram_gb": max_vram_gb,
        "blockers": blockers,
        "warnings": warnings,
        "model_advice": model_advice,
    }


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Assess Wan2GP install readiness")
    parser.parse_args()

    system_info = _collect_system_info()
    gpu_report = build_report()
    recommendation = _build_recommendation(gpu_report, system_info)

    report = {
        "status": "success",
        "system": {
            "os": system_info.os_name,
            "python_version": system_info.python_version,
            "total_ram_gb": system_info.total_ram_gb,
            "free_disk_gb": system_info.free_disk_gb,
        },
        "gpu": gpu_report,
        "recommendation": recommendation,
    }
    print(json.dumps(report, indent=2))

    return 0 if recommendation["verdict"] != "not_recommended" else 2


if __name__ == "__main__":
    sys.exit(main())
