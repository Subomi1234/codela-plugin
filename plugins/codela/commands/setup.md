---
description: Connect this repo to Codela — opens a browser page to pick your observability tool and service
allowed-tools: Bash(python3:*)
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codela_lessons.py" --setup || true`

Relay the result above to the user in a sentence or two, keeping any link exactly as written.
Never ask the user to paste an API key, token or Codela key into this chat — keys go only into the browser page.
If setup finished, tell them new sessions in this repo will start with its production lessons, and that `/codela:lessons` shows them.
