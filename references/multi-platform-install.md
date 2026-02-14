# Multi-Platform Install

Use `scripts/install_skill.py` to install this skill for Claude, Codex, or Gemini.

Codex-first default:
```bash
python scripts/install_skill.py --scope user
```

## User Scope

```bash
python scripts/install_skill.py --platform claude --scope user
python scripts/install_skill.py --platform codex --scope user
python scripts/install_skill.py --platform gemini --scope user
```

## Project Scope

```bash
python scripts/install_skill.py --platform claude --scope project --project-root <PROJECT_ROOT>
python scripts/install_skill.py --platform codex --scope project --project-root <PROJECT_ROOT>
python scripts/install_skill.py --platform gemini --scope project --project-root <PROJECT_ROOT>
```

## Paths Used

- Claude: `~/.claude/skills/wan2gp-operator` or `<project>/.claude/skills/wan2gp-operator`
- Codex: `~/.agents/skills/wan2gp-operator` or `<project>/.agents/skills/wan2gp-operator`
- Gemini: `~/.gemini/skills/wan2gp-operator` or `<project>/.gemini/skills/wan2gp-operator`
