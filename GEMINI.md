# Wan2GP Operator

Operate Wan2GP queues safely and deterministically.

## Primary Commands

```bash
python scripts/detect_gpu.py
python scripts/plan_run.py --wan-root <WAN2GP_ROOT> --process <QUEUE_OR_SETTINGS>
python scripts/run_headless.py --wan-root <WAN2GP_ROOT> --process <QUEUE_OR_SETTINGS> --dry-run
python scripts/run_headless.py --wan-root <WAN2GP_ROOT> --process <QUEUE_OR_SETTINGS> --log-file logs/wan2gp.log
python scripts/diagnose_failure.py --log-file logs/wan2gp.log
```

## Required Inputs

- `wan_root`: folder containing `wgp.py`
- `process`: queue/settings file (`.zip` or `.json`)
- optional `output_dir` and runtime tuning flags

## Operating Rule

Run dry-run first unless the user explicitly asks to skip it.
