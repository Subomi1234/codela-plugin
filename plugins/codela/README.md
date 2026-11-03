<p align="center"><img src="logo.png" width="96" alt="Codela"></p>

# Codela plugin for Claude Code

Loads the production lessons Codela learned from real incidents in your repo
into every Claude Code session, so the agent doesn't repeat them.

## Where it works

| | How |
|---|---|
| **Claude Code in a terminal** | Install the plugin (above) and run `/codela:setup`. |
| **Claude desktop app** | Click **+** next to the prompt box → **Add plugins** → add the marketplace `Subomi1234/codela-plugin` and install **codela**, then run `/codela:setup`. |
| **Claude Code on the web** (and desktop cloud sessions) | Cloud sessions don't load plugins, so `/codela:setup` adds a small hook to your repo instead: `.claude/settings.json`, `.claude/codela/codela_lessons.py` and `.claude/commands/codela-lessons.md`. **Commit them.** Then, once per cloud environment at claude.ai/code → environment settings: add the variable `CODELA_API_KEY` (your Codela key, from usecodela.com/connect → More options), and under network access choose **Custom** and allow `api.usecodela.com`. In cloud sessions, `/codela-lessons` shows the lessons. |

The committed `.claude/settings.json` also offers the Codela plugin to
teammates when they open the repo on their own machines.

## What it does

- **On session start** (`SessionStart` hook): reads `owner/name` from the
  repo's git remote, fetches `GET <server>/lessons?repo=owner/name&format=context`
  from Codela, and adds the lessons to the session context. Every lesson's
  one-line summary is always included; full detail is added for the most
  severe lessons within Claude Code's context-size limit.
  If Codela is unreachable it uses the last cached copy; it never fails the session.
- **`/codela:setup`**: connects this repo to Codela. It reads the repo from
  git, opens a browser page where you pick your observability tool (SigNoz,
  Datadog, New Relic or Grafana), paste a read-only key and confirm the
  service, then saves your Codela key to `~/.codela/credentials.json`.
  Keys never pass through the chat. Teammates in an already-linked workspace
  just install the plugin and run `/codela:setup` once.
- **`/codela:lessons [topic]`**: shows every lesson for this repo with its
  production evidence.

## Install

```
/plugin marketplace add Subomi1234/codela-plugin
/plugin install codela@codela
/codela:setup
```

Options (`/plugin configure codela@codela`):

| Option | Default | |
|---|---|---|
| `api_key` | — | Optional: a Codela key you already have. `/codela:setup` saves one for you. |
| `server_url` | `https://api.usecodela.com` | Codela backend |
| `repo` | *(from git remote)* | `owner/name` override |

For local development, `CODELA_SERVER_URL` and `CODELA_API_KEY` override the options:

```
CODELA_SERVER_URL=http://127.0.0.1:3000 claude --plugin-dir ./plugins/codela
```

Requires `python3` and `git` on PATH (standard library only).
