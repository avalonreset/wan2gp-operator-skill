---
name: wan2gp-operator
description: >
  Codex-first operations suite for Wan2GP. Assesses installation readiness,
  plans or executes setup, composes Wan2GP settings JSON from natural-language
  prompts with VRAM-aware defaults, runs `wgp.py --process` headless jobs,
  diagnoses failures, checks/summarizes upstream releases, and orchestrates
  music-video pipelines from an audio track. Use when user
  says "set up wan2gp", "is my machine good for wan2gp", "run this wan2gp
  queue", "generate wan2gp settings from this prompt", "wan2gp failed",
  "check wan2gp updates", "what changed in the new wan2gp release", "make a
  music video from this song", or "beat-sync wan2gp clips".
---

# Wan2GP Operator

Run Wan2GP from terminal as a guided operating layer over the UI and headless
engine. Default to deterministic scripts, JSON outputs, and explicit safety
checks.

## Process

### Step 1: Assess Readiness (Before Install)

Run:
```bash
python scripts/wan2gp_operator.py bootstrap
```

Use output verdict:
- `recommended`: proceed with standard setup
- `possible_with_constraints`: proceed with conservative presets
- `not_recommended`: explain blockers before install

### Step 2: Setup or Update Wan2GP

One-command from-scratch install + launch:
```bash
python scripts/wan2gp_operator.py bootstrap --execute --launch-ui
```

Manual setup plan (defaults to `./Wan2GP` if path omitted):
```bash
python scripts/wan2gp_operator.py setup
python scripts/wan2gp_operator.py setup --execute
```

Launch UI later:
```bash
python scripts/wan2gp_operator.py launch-ui --wan-root <WAN2GP_ROOT>
```

### Step 3: Compose Settings from Prompt

Generate process JSON from natural-language intent:
```bash
python scripts/wan2gp_operator.py compose \
  --prompt "<PROMPT>" \
  --quality balanced \
  --duration-seconds 5
```

### Step 4: Build and Validate Headless Plan

Plan run:
```bash
python scripts/wan2gp_operator.py plan \
  --wan-root <WAN2GP_ROOT> \
  --process <QUEUE_OR_SETTINGS_FILE_OR_COMPOSED_JSON> \
  --output-dir <OUTPUT_DIR>
```

Dry-run:
```bash
python scripts/wan2gp_operator.py run \
  --wan-root <WAN2GP_ROOT> \
  --process <QUEUE_OR_SETTINGS_FILE_OR_COMPOSED_JSON> \
  --output-dir <OUTPUT_DIR> \
  --dry-run
```

### Step 5: Run Batch Generation

Full run with logs:
```bash
python scripts/wan2gp_operator.py run \
  --wan-root <WAN2GP_ROOT> \
  --process <QUEUE_OR_SETTINGS_FILE_OR_COMPOSED_JSON> \
  --output-dir <OUTPUT_DIR> \
  --log-file <LOG_FILE>
```

### Step 6: Diagnose Failures

Run:
```bash
python scripts/wan2gp_operator.py diagnose --log-file <LOG_FILE>
```

### Step 7: Track New Releases

Run:
```bash
python scripts/wan2gp_operator.py updates --wan-root <WAN2GP_ROOT>
```

### Step 8: Evolve Capability State

Inspect learned compatibility and ingest failed logs:
```bash
python scripts/wan2gp_operator.py evolve --wan-root <WAN2GP_ROOT>
python scripts/wan2gp_operator.py evolve --wan-root <WAN2GP_ROOT> --log-file <LOG_FILE>
```

`run` now auto-retries once for known CLI incompatibilities and stores learned state
in `<WAN2GP_ROOT>/.wan2gp_operator_state.json`.
It also learns unsupported attention backends from logs and auto-falls back to `sdpa`.

### Step 9: Build A Music Video Pipeline

Single command:
```bash
python scripts/wan2gp_operator.py music-video \
  --audio <SONG_FILE> \
  --theme "<CREATIVE_DIRECTION>" \
  --wan-root <WAN2GP_ROOT> \
  --execute-generation \
  --evolve-on-failure
```

Stage commands:
```bash
python scripts/wan2gp_operator.py music-analyze --audio <SONG_FILE>
python scripts/wan2gp_operator.py music-plan --analysis <AUDIO_ANALYSIS_JSON> --theme "<CREATIVE_DIRECTION>"
python scripts/wan2gp_operator.py music-generate --plan <PLAN_JSON> --wan-root <WAN2GP_ROOT> --execute-generation
python scripts/wan2gp_operator.py music-assemble --audio <SONG_FILE> --manifest <GENERATION_MANIFEST_JSON>
```

## Quality Gates

Before marking a run as complete:
- [ ] Readiness assessment completed for new installs
- [ ] `wgp.py` exists in provided Wan2GP root
- [ ] Process input exists with `.zip` or `.json`
- [ ] Dry-run passed (or user explicitly skipped it)
- [ ] Full run command and log file path captured
- [ ] Failure diagnosis produced when exit status was non-zero
- [ ] Update check performed when user asks about latest release changes
- [ ] Capability state reviewed/updated after repeat failures
- [ ] For music-video runs: analysis, plan, generation manifest, and assembly outputs captured

## Output Contract

Return:
- Exact command used
- Settings file path (if composed)
- Output directory (if provided)
- Exit status and elapsed time
- If failed: root causes and next command to try
- If update exists: version, highlights, and safe update commands
- If auto-adjusted: include retry attempts, applied adjustments, and state file path

## Codex Notes

- Codex trigger: description routing or `$wan2gp-operator`
- Use `python scripts/wan2gp_operator.py <command>` as primary interface
- Use direct scripts only when user asks for low-level control

## Reference Files

Load on-demand as needed:
- `references/codex-workflows.md` -- Codex-first command cookbook
- `references/headless-runbook.md` -- End-to-end queue workflow
- `references/performance-guide.md` -- VRAM-to-settings decision table
- `references/multi-platform-install.md` -- install path notes

## Examples

### Example: First-Time Setup
User says: "Install Wan2GP if my machine can handle it."
Actions:
1. `wan2gp_operator.py bootstrap`
2. `wan2gp_operator.py bootstrap --execute --launch-ui`
3. If blocked, explain readiness blockers and alternatives

### Example: Terminal-First Prompt Flow
User says: "Make a 6-second cinematic rain alley clip, no UI clicking."
Actions:
1. `wan2gp_operator.py compose --prompt ... --duration-seconds 6`
2. `wan2gp_operator.py run ... --dry-run`
3. `wan2gp_operator.py run ... --log-file ...`

### Example: Update Intelligence
User says: "Did Wan2GP ship anything important this week?"
Actions:
1. `wan2gp_operator.py updates --wan-root ...`
2. Summarize highlights in plain language
3. Provide update commands if newer version exists

### Example: Recursive Improvement
User says: "It failed again, make it learn and retry smarter."
Actions:
1. `wan2gp_operator.py run ... --log-file ...`
2. `wan2gp_operator.py evolve --wan-root ... --log-file ...`
3. Rerun with evolved recommendations (or rely on auto-adjust retry behavior)

### Example: Music Video From A Song
User says: "Take this track and make a cohesive music video."
Actions:
1. `wan2gp_operator.py music-video --audio ... --theme ... --wan-root ... --execute-generation`
2. If quality is weak, rerun with `--evolve-on-failure` and adjusted theme
3. Return output video path plus plan/manifest files

