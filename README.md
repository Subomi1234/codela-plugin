<p align="center"><img src="plugins/codela/logo.png" width="96" alt="Codela"></p>

# Codela for Claude Code

Production memory for AI coding agents. Codela watches your deploys through
your observability tool (SigNoz, Datadog, New Relic or Grafana), works out
which code changes caused real production regressions, and writes lessons
from them. This plugin loads your repo's lessons into every Claude Code
session, so the agent doesn't repeat mistakes your production has already
paid for.

## Install

```
/plugin marketplace add Subomi1234/codela-plugin
/plugin install codela@codela
/codela:setup
```

`/codela:setup` reads the repo you're in from git and opens a browser page
where you pick your observability tool, paste a read-only key and confirm the
service. Keys go into that page, never into the chat. Claude Code then picks
up your Codela key automatically.

## Commands

- `/codela:setup`: connect this repo to Codela.
- `/codela:lessons [topic]`: show this repo's production lessons and their evidence.

Lessons also load automatically at the start of every session.

## What data the plugin sends

- The plugin calls `https://api.usecodela.com` only.
- It sends this repo's `owner/name` (from `git remote origin`) and your
  Codela key, and receives the repo's lessons.
- `/codela:setup` also sends `owner/name` to start setup. Observability
  credentials are entered in the browser, not in the plugin.
- It saves your Codela key to `~/.codela/credentials.json` (readable only by
  you), and caches lessons in the plugin's data folder so a session still
  starts if Codela is unreachable.
- It sends no source code.

See https://usecodela.com for how the Codela service handles your
observability data.

## Requirements

`python3` and `git` on your PATH. The plugin uses only the Python standard
library.

## License

Copyright © Codela. All rights reserved. You may install and use the plugin
with the Codela service; see [LICENSE](LICENSE).
