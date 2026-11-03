---
description: Show the production lessons Codela has learned for this repo, with their evidence
allowed-tools: Bash(python3:*)
---

These are the production lessons Codela learned from real incidents in this repo:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codela_lessons.py" --full || true`

Summarize them for the user: one line per lesson saying what broke in production and what to do differently. If the user passed arguments, focus on lessons relevant to: $ARGUMENTS
