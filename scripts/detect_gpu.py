#!/usr/bin/env python3
"""
Detect local GPU hardware and suggest Wan2GP defaults.

Usage:
  python scripts/detect_gpu.py
"""

from __future__ import annotations

import json
import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


@dataclass
class GpuInfo:
    """Structured GPU information."""

    name: str
    vram_gb: float
    driver: str | None = None


def detect_nvidia() -> list[GpuInfo]:
    """Read NVIDIA GPU info from nvidia-smi."""
    if not shutil.which("nvidia-smi"):
        return []

    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return []

    gpus: list[GpuInfo] = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        name = parts[0]
        try:
            mem_mib = float(parts[1])
        except ValueError:
            continue
        driver = parts[2] if len(parts) >= 3 else None
        gpus.append(GpuInfo(name=name, vram_gb=round(mem_mib / 1024.0, 1), driver=driver))
    return gpus


def detect_amd_rocm() -> bool:
    """Return True if ROCm tooling appears available."""
    return bool(shutil.which("rocm-smi"))


def recommend_from_vram(max_vram_gb: float) -> dict[str, Any]:
    """Map VRAM tiers to stable starter settings."""
    if max_vram_gb <= 8:
        return {
            "model_preset": "t2v-1-3B",
            "attention": "sdpa",
            "profile": "4",
            "teacache": 1.5,
            "compile": False,
            "rationale": "Lowest-risk profile for 6-8GB VRAM to minimize OOM.",
        }
    if max_vram_gb <= 12:
        return {
            "model_preset": "t2v-14B",
            "attention": "sdpa",
            "profile": "4",
            "teacache": 1.5,
            "compile": False,
            "rationale": "Balanced profile for 10-12GB VRAM; fallback to 1.3B if unstable.",
        }
    if max_vram_gb <= 20:
        return {
            "model_preset": "t2v-14B",
            "attention": "sage",
            "profile": "3",
            "teacache": 2.0,
            "compile": True,
            "rationale": "Higher throughput profile for mid/high VRAM cards.",
        }
    return {
        "model_preset": "t2v-14B",
        "attention": "sage2",
        "profile": "3",
        "teacache": 2.0,
        "compile": True,
        "rationale": "Aggressive profile for 24GB+ class hardware.",
    }


def build_report() -> dict[str, Any]:
    """Build hardware detection report."""
    nvidia_gpus = detect_nvidia()
    if nvidia_gpus:
        max_vram = max(gpu.vram_gb for gpu in nvidia_gpus)
        return {
            "status": "success",
            "backend": "nvidia",
            "gpus": [
                {"name": gpu.name, "vram_gb": gpu.vram_gb, "driver": gpu.driver}
                for gpu in nvidia_gpus
            ],
            "recommended_defaults": recommend_from_vram(max_vram),
        }

    if detect_amd_rocm():
        return {
            "status": "success",
            "backend": "amd",
            "gpus": [],
            "recommended_defaults": {
                "model_preset": "t2v-1-3B",
                "attention": "sdpa",
                "profile": "4",
                "teacache": 1.5,
                "compile": False,
                "rationale": "ROCm detected. Start conservative, then tune by test runs.",
            },
        }

    return {
        "status": "success",
        "backend": "unknown",
        "gpus": [],
        "recommended_defaults": {
            "model_preset": "t2v-1-3B",
            "attention": "sdpa",
            "profile": "4",
            "teacache": 1.5,
            "compile": False,
            "rationale": "No GPU tooling detected. Use safe defaults and verify manually.",
        },
        "warning": "Neither nvidia-smi nor rocm-smi was detected on PATH.",
    }


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Detect GPU and suggest Wan2GP defaults")
    parser.parse_args()
    report = build_report()
    print(json.dumps(report, indent=2))
    return 0 if report.get("status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
