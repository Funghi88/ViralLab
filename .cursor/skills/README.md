# Cursor skills (canonical copy elsewhere)

Shared Agent skills are **not** duplicated in this repo. They live in **`~/cursor-skills-source`** (one tree for all projects).

**Full usage (any project, Chinese):** `~/cursor-skills-source/CURSOR_SKILLS_SOURCE.md`

**On this machine**, after editing skills in `~/cursor-skills-source`, run:

```bash
~/cursor-skills-source/link-to-cursor.sh
```

That links `~/.cursor/skills/<name>` → `~/cursor-skills-source/<name>` so Cursor loads them in every workspace.

**New clone / teammate:** copy or clone the skills source to `~/cursor-skills-source`, then run the same script.

Repo-only or secret skills (rare) can still be added here as `<skill-name>/SKILL.md`.
