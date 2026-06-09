# Codex Index

Read root `AGENTS.md` first. It is the canonical AI-agent contract for this
repository.

Use these Codex phase playbooks when a task belongs mainly to one remaining MVP
phase:

- `agents/phase-3b-baseline.md` for post-session baseline computation.
- `agents/phase-5b-arc-batch.md` for ARC batch processing and interpretation.
- `agents/phase-4b-operator-surface.md` for thin CLI/notebook review and export.

If a task spans phases, preserve the data order: capture first, baseline second,
ARC batch third, operator review/export last.

There are intentionally no project skills in this pass. Add skills later under
`.codex/skills/<skill-name>/SKILL.md` if the workflow needs reusable procedural
context.
