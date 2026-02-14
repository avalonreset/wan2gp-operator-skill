# Changelog

## 0.3.0

- Added Phase 1 music-video pipeline:
  - `music-analyze` (audio BPM/beat/section analysis)
  - `music-plan` (beat-aligned shot planning and prompts)
  - `music-generate` (multi-take Wan2GP generation with optional evolve-on-failure)
  - `music-assemble` (ffmpeg-based clip normalization, concat, and audio mux)
  - `music-video` (one-command orchestrator)
- Extended unified operator command map for all new music-video commands
- Added docs for one-command and stage-by-stage music-video workflows

## 0.2.0

- Added quality-feedback evolution flow (`evolve --quality-feedback ...`)
- Added quality recommendations output in headless runs
- Improved compose defaults for Wan2.2 quality runs
- Added safer runtime recommendations for quality-focused generation

## 0.1.0

- Initial public release
- Bootstrap, compose, run, diagnose, updates, evolve workflows
- Codex-first skill contract and references
