# Wan2GP Performance Guide

Starter defaults by VRAM tier for stable first runs:

| VRAM | Model Preset | Attention | Profile | TeaCache | Compile |
|------|---------------|-----------|---------|----------|---------|
| 6-8GB | `t2v-1-3B` | `sdpa` | `4` | `1.5` | Off |
| 10-12GB | `t2v-14B` | `sdpa` | `4` | `1.5` | Off |
| 16-20GB | `t2v-14B` | `sage` | `3` | `2.0` | On |
| 24GB+ | `t2v-14B` | `sage2` | `3` | `2.0` | On |

## Known Tradeoffs

- `sdpa`: safest compatibility, slower than Sage/Sage2.
- `sage`/`sage2`: higher throughput, but requires dependency compatibility.
- `profile 4`: best fallback when facing OOM.
- `profile 3`: higher speed if VRAM headroom exists.
- `teacache`: speed boost with potential quality tradeoff at higher values.

## Common Fallback Path

If a run fails with OOM:
1. Switch to `--model-preset t2v-1-3B`.
2. Force `--attention sdpa --profile 4`.
3. Lower generation complexity (frames, steps, resolution) in queue/settings.

## Terminal-First Tip

Use:
```bash
python scripts/wan2gp_operator.py compose --prompt "<PROMPT>" --quality draft
```
Then run dry-run before full generation.

