# Contributing

Corrections from real-world use are the most valuable thing you can send: a tool flag that changed, a step that didn't work for you, a case the checks miss. Speculative rewrites are not.

## Anatomy

- `skills/<name>/SKILL.md` — the workflow (under ~300 lines; deep detail in `references/`)
- `tools/autopsy` — the CLI the skill leans on

## Before a PR

```bash
pip install pytest pyyaml ./tools/autopsy
python scripts/validate_skills.py
python -m pytest -q
```

Keep the SKILL.md Scope section intact — it is part of the contract. MIT.
