#!/usr/bin/env python3
"""
Analyze an audio track for music-video planning.

Usage:
  python scripts/music_analyze.py --audio ./song.mp3
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import math
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze audio for Wan2GP music-video planning")
    parser.add_argument("--audio", required=True, help="Path to input audio file (mp3/wav/flac/m4a)")
    parser.add_argument("--output", help="Output analysis JSON path")
    parser.add_argument("--min-section-seconds", type=float, default=8.0, help="Minimum section duration")
    parser.add_argument("--max-energy-points", type=int, default=192, help="Max points in energy curve")
    parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe executable path")
    return parser.parse_args()


def _run_json_command(command: list[str]) -> dict[str, Any]:
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip() or "Command failed")
    try:
        loaded = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse command JSON output: {exc}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError("Expected command to return a JSON object.")
    return loaded


def _probe_audio(audio_path: Path, ffprobe_bin: str) -> dict[str, Any]:
    if shutil.which(ffprobe_bin) is None:
        raise FileNotFoundError(f"ffprobe not found on PATH: {ffprobe_bin}")

    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,sample_rate,channels",
        "-of",
        "json",
        str(audio_path),
    ]
    probe = _run_json_command(command)
    streams = probe.get("streams", [])
    audio_stream = None
    if isinstance(streams, list):
        for stream in streams:
            if isinstance(stream, dict) and stream.get("codec_type") == "audio":
                audio_stream = stream
                break
    fmt = probe.get("format", {})
    duration = float((fmt or {}).get("duration", 0.0) or 0.0)
    if duration <= 0.0:
        raise RuntimeError(f"Could not determine audio duration for: {audio_path}")
    return {
        "duration_seconds": duration,
        "codec_name": (audio_stream or {}).get("codec_name"),
        "sample_rate_hz": int((audio_stream or {}).get("sample_rate", 0) or 0),
        "channels": int((audio_stream or {}).get("channels", 0) or 0),
    }


def _clip_round(values: list[float], duration: float) -> list[float]:
    out: list[float] = []
    for value in values:
        if value < 0:
            continue
        if value > duration:
            continue
        out.append(round(float(value), 4))
    return out


def _fallback_beats(duration_seconds: float) -> tuple[float, list[float]]:
    bpm = 120.0
    beat_interval = 60.0 / bpm
    beat_count = max(1, int(math.floor(duration_seconds / beat_interval)))
    beats = [i * beat_interval for i in range(beat_count)]
    return bpm, _clip_round(beats, duration_seconds)


def _infer_bpm_from_beats(beats: list[float], fallback_bpm: float) -> float:
    if len(beats) < 3:
        return fallback_bpm
    intervals = [beats[i + 1] - beats[i] for i in range(len(beats) - 1)]
    intervals = [x for x in intervals if x > 0]
    if not intervals:
        return fallback_bpm
    med = median(intervals)
    if med <= 0:
        return fallback_bpm
    bpm = 60.0 / med
    if bpm < 40 or bpm > 220:
        return fallback_bpm
    return bpm


def _snap_to_nearest_beat(target: float, beats: list[float]) -> float:
    if not beats:
        return target
    nearest = min(beats, key=lambda beat: abs(beat - target))
    return float(nearest)


def _build_sections(duration_seconds: float, beats: list[float], min_section_seconds: float) -> list[dict[str, Any]]:
    if duration_seconds <= 45:
        layout = [
            ("intro", 0.14),
            ("verse", 0.24),
            ("chorus", 0.22),
            ("verse", 0.2),
            ("chorus", 0.2),
        ]
    else:
        layout = [
            ("intro", 0.1),
            ("verse", 0.16),
            ("pre-chorus", 0.1),
            ("chorus", 0.14),
            ("verse", 0.16),
            ("chorus", 0.14),
            ("bridge", 0.1),
            ("chorus", 0.1),
        ]

    boundaries: list[float] = [0.0]
    cursor = 0.0
    for _, ratio in layout:
        cursor += duration_seconds * ratio
        snapped = _snap_to_nearest_beat(cursor, beats)
        boundaries.append(min(duration_seconds, max(0.0, snapped)))
    boundaries.append(duration_seconds)

    min_span = max(2.0, float(min_section_seconds))
    cleaned = [boundaries[0]]
    for boundary in boundaries[1:]:
        if boundary - cleaned[-1] < min_span:
            continue
        cleaned.append(boundary)
    if cleaned[-1] < duration_seconds:
        cleaned[-1] = duration_seconds
    if cleaned[0] != 0.0:
        cleaned.insert(0, 0.0)

    labels = [label for label, _ in layout]
    energy_by_label = {
        "intro": "low",
        "verse": "medium",
        "pre-chorus": "medium",
        "chorus": "high",
        "bridge": "medium",
        "outro": "low",
    }
    sections: list[dict[str, Any]] = []
    for idx in range(len(cleaned) - 1):
        start = round(cleaned[idx], 4)
        end = round(cleaned[idx + 1], 4)
        if end <= start:
            continue
        if idx < len(labels):
            label = labels[idx]
        elif idx == len(cleaned) - 2:
            label = "outro"
        else:
            label = "section"
        sections.append(
            {
                "label": label,
                "start_sec": start,
                "end_sec": end,
                "energy": energy_by_label.get(label, "medium"),
            }
        )
    if not sections:
        sections = [
            {"label": "section", "start_sec": 0.0, "end_sec": round(duration_seconds, 4), "energy": "medium"}
        ]
    return sections


def _try_librosa_analysis(
    audio_path: Path,
    duration_seconds: float,
    min_section_seconds: float,
    max_energy_points: int,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    librosa_spec = importlib.util.find_spec("librosa")
    if librosa_spec is None:
        raise ModuleNotFoundError("librosa is not installed")

    librosa = importlib.import_module("librosa")
    numpy = importlib.import_module("numpy")

    y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, trim=False)
    if hasattr(tempo, "item"):
        tempo = tempo.item()
    bpm = float(tempo or 0.0)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    beats = _clip_round([float(value) for value in beat_times], duration_seconds)
    if len(beats) < 4:
        fallback_bpm, fallback_beats = _fallback_beats(duration_seconds)
        warnings.append("Beat tracking found too few beats; used fallback beat grid.")
        bpm = fallback_bpm
        beats = fallback_beats
    else:
        bpm = _infer_bpm_from_beats(beats, max(1.0, bpm))

    downbeats = beats[::4] if beats else []
    rms = librosa.feature.rms(y=y)[0]
    times = librosa.times_like(rms, sr=sr)
    stride = max(1, int(math.ceil(len(rms) / max(1, max_energy_points))))
    energy_curve: list[dict[str, float]] = []
    for idx in range(0, len(rms), stride):
        point = {
            "time_sec": round(float(times[idx]), 4),
            "energy": round(float(rms[idx]), 6),
        }
        if point["time_sec"] <= duration_seconds:
            energy_curve.append(point)
    if not energy_curve:
        energy_curve = [{"time_sec": 0.0, "energy": 0.0}]

    sections = _build_sections(duration_seconds, beats, min_section_seconds)
    return {
        "backend": "librosa",
        "bpm": round(bpm, 3),
        "beats": beats,
        "downbeats": _clip_round(downbeats, duration_seconds),
        "sections": sections,
        "energy_curve": energy_curve,
    }, warnings


def _resolve_output_path(path_arg: str | None) -> Path:
    if path_arg:
        return Path(path_arg).expanduser().resolve()
    folder = Path.cwd() / "wan2gp_music_jobs" / "analysis"
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return (folder / f"audio-analysis-{ts}.json").resolve()


def main() -> int:
    try:
        args = _parse_args()
        audio_file = Path(args.audio).expanduser().resolve()
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file}")
        if not audio_file.is_file():
            raise ValueError(f"Audio path is not a file: {audio_file}")

        probe = _probe_audio(audio_file, args.ffprobe_bin)
        duration_seconds = float(probe["duration_seconds"])

        warnings: list[str] = []
        try:
            analysis, librosa_warnings = _try_librosa_analysis(
                audio_path=audio_file,
                duration_seconds=duration_seconds,
                min_section_seconds=args.min_section_seconds,
                max_energy_points=args.max_energy_points,
            )
            warnings.extend(librosa_warnings)
        except Exception as exc:
            fallback_bpm, fallback_beats = _fallback_beats(duration_seconds)
            warnings.append(f"librosa analysis unavailable; fallback used ({exc}).")
            analysis = {
                "backend": "ffprobe-fallback",
                "bpm": fallback_bpm,
                "beats": fallback_beats,
                "downbeats": fallback_beats[::4],
                "sections": _build_sections(duration_seconds, fallback_beats, args.min_section_seconds),
                "energy_curve": [{"time_sec": 0.0, "energy": 0.0}],
            }

        output_path = _resolve_output_path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "status": "success",
            "audio_file": str(audio_file),
            "analysis_file": str(output_path),
            "duration_seconds": round(duration_seconds, 4),
            "audio_probe": probe,
            "backend": analysis["backend"],
            "bpm": analysis["bpm"],
            "beat_count": len(analysis["beats"]),
            "beats": analysis["beats"],
            "downbeats": analysis["downbeats"],
            "sections": analysis["sections"],
            "energy_curve": analysis["energy_curve"],
            "warnings": warnings,
        }
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
