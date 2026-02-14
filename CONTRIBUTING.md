# Contributing

## Ground Rules

- Keep changes deterministic and script-first.
- Prefer additive improvements over broad rewrites.
- Preserve CLI stability of `scripts/wan2gp_operator.py`.

## Local Validation

Use the Wan2GP venv when available:

```bash
python -m py_compile scripts/*.py
python scripts/wan2gp_operator.py compose --prompt "smoke test" --quality balanced --duration-seconds 2
```

For run-path updates, always validate:

1. Dry-run path
2. Full run path
3. Failure diagnosis path
4. Evolve path

## Pull Request Focus

- Bug + risk first
- Repro command
- Before/after behavior
- Any new defaults and tradeoffs

