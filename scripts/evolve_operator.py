#!/usr/bin/env python3
"""
Inspect and evolve Wan2GP operator compatibility state.

Usage:
  python scripts/evolve_operator.py --wan-root /path/to/Wan2GP
  python scripts/evolve_operator.py --wan-root /path/to/Wan2GP --log-file logs/failed-run.log
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _wan2gp_common import (
    append_incident,
    is_attention_known_unsupported,
    is_flag_known_unsupported,
    load_operator_state,
    mark_unsupported_arg,
    mark_unsupported_attention,
    operator_state_path,
    save_operator_state,
)


def _parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description="Evolve Wan2GP operator state from incidents")
    parser.add_argument("--wan-root", required=True, help="Wan2GP root path")
    parser.add_argument("--log-file", help="Optional run log to ingest")
    parser.add_argument(
        "--quality-feedback",
        choices=["good", "bad"],
        help="Subjective quality feedback for latest run (good|bad)",
    )
    parser.add_argument(
        "--process-file",
        help="Optional process/settings JSON used in the run (helps evolve next preset)",
    )
    parser.add_argument(
        "--write-suggested-settings",
        help="Optional output path to write evolved next-run settings JSON",
    )
    parser.add_argument("--max-incidents", type=int, default=8, help="Max recent incidents to return")
    return parser.parse_args()


def _ingest_log_if_present(state: dict, log_file: Path | None) -> list[str]:
    """Ingest known failure signatures from a log file."""
    updates: list[str] = []
    if log_file is None:
        return updates
    if not log_file.exists():
        updates.append(f"Log file not found: {log_file}")
        return updates

    text = log_file.read_text(encoding="utf-8", errors="replace")
    if "unrecognized arguments: --teacache" in text:
        mark_unsupported_arg(state, "--teacache", evidence="Found in ingested log file.")
        append_incident(
            state,
            "unsupported_cli_argument",
            {"flag": "--teacache", "source_log": str(log_file)},
        )
        updates.append("Learned incompatibility: --teacache unsupported.")
    if "attention mode 'sage2'. However it is not installed or supported" in text:
        mark_unsupported_attention(state, "sage2", evidence="Found in ingested log file.")
        append_incident(
            state,
            "unsupported_attention_mode",
            {"mode": "sage2", "source_log": str(log_file)},
        )
        updates.append("Learned incompatibility: attention mode 'sage2' unsupported.")
    return updates


def _load_json_file(path: Path) -> dict:
    """Load JSON object from disk, returning empty object if unreadable."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    return {}


def _prompt_mentions_text_rendering(prompt: str) -> bool:
    """Detect prompt patterns that often fail in raw t2v models."""
    lowered = prompt.lower()
    risky_terms = ("logo", "text", "typography", "website", "url", ".com", ".pro", "domain")
    return any(term in lowered for term in risky_terms)


def _evolve_settings_for_quality_bad(process_settings: dict) -> tuple[dict, list[str]]:
    """Build a safer next-run recipe after user says output quality is bad."""
    if not isinstance(process_settings, dict):
        return {}, ["No process settings loaded; cannot evolve concrete parameters."]

    evolved = dict(process_settings)
    notes: list[str] = []

    evolved["resolution"] = "832x480"
    notes.append("Locked resolution to 832x480 for stability.")

    model_type = str(evolved.get("model_type", ""))
    if model_type in {"t2v", "t2v_14B"}:
        evolved["model_type"] = "t2v_2_2"
        notes.append("Switched model_type to t2v_2_2 for stronger quality baseline.")

    evolved["num_inference_steps"] = min(32, max(24, int(evolved.get("num_inference_steps", 28) or 28)))
    evolved["video_length"] = min(49, max(33, int(evolved.get("video_length", 41) or 41)))
    evolved["guidance_phases"] = 2
    evolved["guidance_scale"] = 4.5
    evolved["guidance2_scale"] = 3.0
    evolved["switch_threshold"] = 875
    evolved["flow_shift"] = 5
    notes.append("Applied quality-stable Wan2.2 core params: steps 24-32, flow_shift 5, cfg 4.5/3.0.")

    prompt = str(evolved.get("prompt", "")).strip()
    if _prompt_mentions_text_rendering(prompt):
        evolved["prompt"] = (
            f"{prompt}. No readable on-screen text or logos; prioritize clear subject, coherent motion, clean lighting."
        )
        notes.append("Prompt requested text/logo/domain content; constrained prompt to avoid text rendering artifacts.")

    negative = str(evolved.get("negative_prompt", "")).strip()
    additions = "text, logo, watermark, blurry, low quality, gray blob, jitter, flicker"
    merged = [part.strip() for part in f"{negative}, {additions}".split(",") if part.strip()]
    deduped = list(dict.fromkeys(merged))
    evolved["negative_prompt"] = ", ".join(deduped)
    notes.append("Strengthened negative prompt against blob/jitter/text artifacts.")

    seed = int(evolved.get("seed", -1) or -1)
    evolved["seed"] = seed if seed >= 0 else 314159
    evolved["output_filename"] = str(evolved.get("output_filename", "wan2gp_evolved_quality")).strip() + "_evolved"
    return evolved, notes


def main() -> int:
    """CLI entrypoint."""
    args = _parse_args()
    wan_root = Path(args.wan_root).expanduser().resolve()
    if not (wan_root / "wgp.py").exists():
        print(
            json.dumps(
                {"status": "error", "error": f"wgp.py not found in {wan_root}"},
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    state = load_operator_state(wan_root)
    state_file = operator_state_path(wan_root)
    log_path = Path(args.log_file).expanduser().resolve() if args.log_file else None
    updates = _ingest_log_if_present(state, log_path)
    process_path = Path(args.process_file).expanduser().resolve() if args.process_file else None
    process_settings = _load_json_file(process_path) if process_path else {}
    evolved_settings: dict = {}
    quality_notes: list[str] = []

    if args.quality_feedback:
        append_incident(
            state,
            f"subjective_quality_{args.quality_feedback}",
            {
                "process_file": str(process_path) if process_path else None,
                "log_file": str(log_path) if log_path else None,
            },
        )
        updates.append(f"Recorded user quality feedback: {args.quality_feedback}.")
        if args.quality_feedback == "bad":
            evolved_settings, quality_notes = _evolve_settings_for_quality_bad(process_settings)
        save_operator_state(wan_root, state)
    elif updates:
        save_operator_state(wan_root, state)

    suggested_settings_file = None
    if args.write_suggested_settings and evolved_settings:
        out_path = Path(args.write_suggested_settings).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(evolved_settings, indent=2), encoding="utf-8")
        suggested_settings_file = str(out_path)

    unsupported = state.get("unsupported_args", {})
    unsupported_attention_modes = state.get("unsupported_attention_modes", {})
    incidents = state.get("incidents", [])
    if not isinstance(incidents, list):
        incidents = []

    recommended_attention = "sdpa" if is_attention_known_unsupported(state, "sage2") else "sage2"
    recommended_flags = {
        "attention": recommended_attention,
        "profile": "3",
        "compile": True,
        "teacache": None if is_flag_known_unsupported(state, "--teacache") else 2.0,
    }
    if args.quality_feedback == "bad":
        recommended_flags = {
            "attention": "sdpa",
            "profile": "3",
            "compile": False,
            "teacache": None,
        }

    run_example = (
        "python scripts/wan2gp_operator.py run --wan-root <WAN2GP_ROOT> --process <SETTINGS_JSON> "
        f"--attention {recommended_flags['attention']} --profile {recommended_flags['profile']}"
        + (" --compile" if recommended_flags["compile"] else "")
        + (f" --teacache {recommended_flags['teacache']}" if recommended_flags["teacache"] is not None else "")
    )

    report = {
        "status": "success",
        "wan_root": str(wan_root),
        "state_file": str(state_file),
        "updates_applied": updates,
        "unsupported_args": unsupported,
        "unsupported_attention_modes": unsupported_attention_modes,
        "recent_incidents": incidents[-max(args.max_incidents, 1) :],
        "quality_feedback": args.quality_feedback,
        "quality_notes": quality_notes,
        "suggested_settings_file": suggested_settings_file,
        "suggested_settings": evolved_settings if evolved_settings else None,
        "recommended_flags": recommended_flags,
        "run_example": run_example,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
