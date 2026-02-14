# Wan2GP Operator

Codex-first terminal operations layer for Wan2GP.

## Unified Interface

Use one command surface:
```bash
python scripts/wan2gp_operator.py <command> [args]
```

Commands:
- `bootstrap`: assess + setup plan (or execute) + optional UI launch
- `assess`: machine readiness and install-worth-it verdict
- `setup`: plan or execute installation/update workflow
- `launch-ui`: open Wan2GP web UI from terminal
- `compose`: create Wan2GP settings JSON from natural-language prompt
- `plan`: build validated `wgp.py --process` command
- `run`: execute headless job with optional dry-run and log capture
- `diagnose`: analyze failures from logs/text
- `updates`: check latest Wan2GP release and summarize highlights

## Typical Flow

1. `python scripts/wan2gp_operator.py assess`
2. `python scripts/wan2gp_operator.py bootstrap --execute --launch-ui`
3. `python scripts/wan2gp_operator.py compose --prompt "<PROMPT>"`
4. `python scripts/wan2gp_operator.py run --wan-root <WAN2GP_ROOT> --process <SETTINGS_JSON> --dry-run`
5. `python scripts/wan2gp_operator.py run --wan-root <WAN2GP_ROOT> --process <SETTINGS_JSON> --log-file logs/wan2gp.log`
6. If failed: `python scripts/wan2gp_operator.py diagnose --log-file logs/wan2gp.log`

## Operating Rules

- Run dry-run before full render unless user explicitly opts out.
- Prefer conservative profile on unknown hardware (`sdpa`, profile `4`).
- Do not claim update status without running `wan2gp_operator.py updates`.

