# Wan2GP Operator

Codex-native command center for Wan2GP.

Stop babysitting sliders. Stop guessing memory limits. Stop burning runs on broken settings.
`wan2gp-operator` turns Wan2GP into a disciplined, terminal-first production workflow.

## Why This Exists

Wan2GP is powerful. But raw power without guardrails is chaos:

- fragile prompts
- wrong runtime flags
- bad checkpoint states
- wasted generations
- no consistent troubleshooting loop

Wan2GP Operator adds the missing layer: operational intelligence.

## Why This Beats Using Wan2GP Directly

Using Wan2GP directly:

- manual setup drift
- easy to misconfigure runs
- no standard dry-run workflow
- no persistent learning from failures
- weak postmortem trail

Using Wan2GP Operator:

- guided install + readiness checks
- VRAM-aware compose flow
- deterministic `run --dry-run` -> `run` pipeline
- structured logs + diagnostics
- evolving compatibility/quality state over time

This is not "more UI." It is better control.

## Core Capabilities

- Bootstrap install and launch
- Hardware/readiness assessment
- Prompt-to-settings composer
- Headless batch execution
- Auto-retry for known CLI incompatibilities
- Failure diagnosis with next-step commands
- Upstream release tracking
- Recursive evolution state (`.wan2gp_operator_state.json`)
- Music-video pipeline (audio analyze -> beat plan -> clip generation -> ffmpeg assembly)

## Workflow

```bash
python scripts/wan2gp_operator.py bootstrap
python scripts/wan2gp_operator.py compose --prompt "cinematic street shot" --quality quality --duration-seconds 4
python scripts/wan2gp_operator.py run --wan-root <WAN2GP_ROOT> --process <settings.json> --dry-run
python scripts/wan2gp_operator.py run --wan-root <WAN2GP_ROOT> --process <settings.json> --log-file logs/run.log
python scripts/wan2gp_operator.py evolve --wan-root <WAN2GP_ROOT> --log-file logs/run.log
```

## Music Video Pipeline (Phase 1)

Turn one track into a structured multi-shot video using Wan2GP as the generation engine.

### End-to-end

```bash
python scripts/wan2gp_operator.py music-video \
  --audio "<SONG>.mp3" \
  --theme "neon summer city, confident performance energy" \
  --wan-root <WAN2GP_ROOT> \
  --execute-generation \
  --evolve-on-failure
```

### Stage-by-stage

```bash
python scripts/wan2gp_operator.py music-analyze --audio "<SONG>.mp3"
python scripts/wan2gp_operator.py music-plan --analysis <audio_analysis.json> --theme "<THEME>"
python scripts/wan2gp_operator.py music-generate --plan <music_plan.json> --wan-root <WAN2GP_ROOT> --execute-generation
python scripts/wan2gp_operator.py music-assemble --audio "<SONG>.mp3" --manifest <generation_manifest.json>
```

### Generated artifacts

- `audio_analysis.json`: duration, BPM, beat grid, sections
- `music_video_plan.json`: beat-aligned shot timeline and prompts
- `generation_manifest.json`: take-by-take compose/run/evolve results
- `music_video_master.mp4`: assembled output with track muxed in

### Dependencies

- Required: `ffmpeg`, `ffprobe`
- Optional but recommended: `librosa` (better beat detection)

## Skill Layout

- `SKILL.md`: skill contract and routing
- `scripts/`: operational CLI tools
- `references/`: practical runbooks and tuning notes
- `agents/`: agent-facing metadata

## Install As A Codex Skill

Copy this folder into your Codex skills directory as `wan2gp-operator`.

Windows example:

```powershell
Copy-Item -Path ".\\wan2gp-operator-skill" -Destination "$env:USERPROFILE\\.codex\\skills\\wan2gp-operator" -Recurse -Force
```

Then restart Codex and invoke the skill by name.

## Positioning

Wan2GP Operator is for builders who care about outcomes, not ritual.
You can keep clicking around and hoping for magic.
Or you can run a repeatable video ops pipeline that gets better every time.
