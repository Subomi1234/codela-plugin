#!/usr/bin/env python3
"""Fetch this repo's production lessons from Codela.

  --hook   SessionStart hook: reads the hook JSON on stdin, prints the lessons
           as additionalContext so they are in the agent's context from the
           first turn. Never fails the session: if Codela is unreachable it
           uses the last cached copy, or prints nothing.
  --full   Print every lesson in full (used by the /codela:lessons command).
  --cloud  Like --hook, but only acts in cloud sessions (Claude Code on the web
           and desktop cloud sessions), which don't load plugins. /codela:setup
           commits a copy of this script into the repo for them.
  --setup  Link this repo to Codela (used by /codela:setup). Opens a browser
           page; the Codela key comes back from the server into
           ~/.codela/credentials.json and is never printed, so it never
           enters the chat.

Standard library only, so it runs anywhere Claude Code does.
"""
import json
import os
import re
import subprocess
import sys
import time
import webbrowser
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_SERVER = "https://api.usecodela.com"
TIMEOUT_S = 8


def server_url():
    # CODELA_SERVER_URL wins so a local or staging backend can be used without
    # changing the plugin's saved configuration.
    return (os.environ.get("CODELA_SERVER_URL")
            or os.environ.get("CLAUDE_PLUGIN_OPTION_SERVER_URL")
            or DEFAULT_SERVER).rstrip("/")


def detect_repo(cwd):
    override = (os.environ.get("CLAUDE_PLUGIN_OPTION_REPO") or "").strip()
    if override:
        return override
    try:
        url = subprocess.run(["git", "-C", cwd, "config", "--get", "remote.origin.url"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return None
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


CREDS = os.path.join(os.path.expanduser("~"), ".codela", "credentials.json")
PENDING = os.path.join(os.path.expanduser("~"), ".codela", "pending_setup.json")
SETUP_WAIT_S = 90


def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _write_private(path, data):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)


def _local(url):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


def api_key():
    # A key saved by setup is tied to the server it came from. A key from the environment or the
    # plugin options goes only to Codela (or a local dev server): a repo's .claude/settings.json can
    # set CODELA_SERVER_URL, and must not be able to send someone's key to its own server.
    env = (os.environ.get("CODELA_API_KEY") or os.environ.get("CLAUDE_PLUGIN_OPTION_API_KEY") or "").strip()
    if env and (server_url() == DEFAULT_SERVER or _local(server_url())):
        return env
    return (_read(CREDS).get(server_url(), {}).get("api_key") or "").strip()


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Codela's API never redirects; following one would carry the key to wherever it points."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirects)


def save_key(key):
    creds = _read(CREDS)
    creds[server_url()] = {"api_key": key}
    _write_private(CREDS, creds)


def request(method, path, body=None, key=None):
    req = urllib.request.Request(f"{server_url()}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if key:
        req.add_header("X-Codela-Key", key)
    try:
        with _opener.open(req, timeout=TIMEOUT_S) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}


def fetch(repo, fmt):
    q = urllib.parse.urlencode({"repo": repo, "format": fmt})
    req = urllib.request.Request(f"{server_url()}/lessons?{q}")
    if api_key():
        req.add_header("X-Codela-Key", api_key())
    with _opener.open(req, timeout=TIMEOUT_S) as r:
        return json.load(r)


def claim_pending():
    """Collect a finished browser setup. Returns the claim result, or None."""
    p = _read(PENDING)
    if not p.get("code") or p.get("server") != server_url():
        return None
    status, res = request("POST", f"/api/setup/sessions/{p['code']}/claim", {"poll_token": p["poll_token"]})
    if status == 404:
        os.remove(PENDING)
        return {"status": "expired"}
    if status != 200 or res.get("status") != "done":
        return res if status == 200 else None
    if res.get("api_key"):
        save_key(res["api_key"])
    os.remove(PENDING)
    return res


def cache_path(repo):
    base = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not base:
        return None
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, re.sub(r"[^A-Za-z0-9_.-]", "_", repo) + ".json")


def hook(cloud=False):
    if cloud and os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return  # local sessions get lessons from the installed plugin instead
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        claim_pending()  # setup finished in the browser since the last session
    except Exception:
        pass
    repo = detect_repo(cwd)
    if not repo:
        return
    cache = cache_path(repo)
    context, note, warn = "", "", ""
    try:
        data = fetch(repo, "context")
        context = data.get("context") or ""
        if cache:
            with open(cache, "w") as f:
                json.dump(data, f)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            warn = "Codela: your Codela key isn't valid any more. Run /codela:setup to reconnect this repo."
    except Exception:
        # Usually network: cloud sessions (Claude Code on the web) block unknown domains by default.
        host = urllib.parse.urlparse(server_url()).hostname
        warn = (f"Codela couldn't reach {host}, so this session has no production lessons. "
                f"In Claude Code on the web, allow {host} in your environment's network access settings.")
        if cache and os.path.exists(cache):
            with open(cache) as f:
                context = json.load(f).get("context") or ""
            note = "\n\n(Codela was unreachable; these are the last cached lessons.)"
    if cloud and not api_key():
        warn = ("Codela: add CODELA_API_KEY to this cloud environment's settings (and allow "
                f"{urllib.parse.urlparse(server_url()).hostname} under network access) so sessions get "
                "this repo's production lessons.")
    out = {}
    if warn and (api_key() or context or cloud):  # only nag people who have set Codela up
        out["systemMessage"] = warn
    if context:
        out["hookSpecificOutput"] = {"hookEventName": "SessionStart", "additionalContext": context + note}
    if out:
        print(json.dumps(out))


def full():
    repo = detect_repo(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if not repo:
        print("Codela: could not determine this repo (no git remote). "
              "Set the plugin's `repo` option to owner/name.")
        return
    try:
        claimed = claim_pending()  # a setup finished in the browser after /codela:setup stopped waiting
    except Exception:
        claimed = None
    if claimed and claimed.get("status") == "done":
        print(f"(Picked up your finished Codela setup for {claimed.get('repo') or repo}.)\n")
    if not api_key():
        print("Codela isn't connected on this machine yet, so there are no lessons to show. "
              "Run /codela:setup to connect this repo.")
        return
    try:
        data = fetch(repo, "json")
    except Exception as e:
        print(f"Codela: could not reach {server_url()} ({e}).")
        return
    lessons = data.get("lessons") or []
    if not lessons:
        print(f"Codela has no production lessons for {repo} yet.")
        return
    print(f"Codela: {len(lessons)} production lesson(s) for {repo}\n")
    for l in lessons:
        src = l.get("source") or {}
        print(f"## {l['name']} [{l['severity']}]")
        print(f"Summary: {l['summary']}")
        if src.get("degradation"):
            print(f"Learned from: {src.get('degradation')}"
                  + (f" (deploy {src['commit_sha']})" if src.get("commit_sha") else ""))
        print(f"Diagnosis: {l['diagnosis']}")
        print(f"Why it matters: {l['why_it_matters']}")
        print("Evidence:\n" + "\n".join(f"- {e}" for e in l["evidence"]))
        print("Applies when:\n" + "\n".join(f"- {e}" for e in l["applies_when"]))
        print("Does not apply when:\n" + "\n".join(f"- {e}" for e in l["does_not_apply_when"]))
        print("Fix strategies:\n" + "\n".join(f"- {e}" for e in l["fix_strategies"]))
        print()


MARKETPLACE_REPO = "Subomi1234/codela-plugin"
REPO_SCRIPT = ".claude/codela/codela_lessons.py"
REPO_COMMAND = ".claude/commands/codela-lessons.md"


def _toplevel(cwd):
    try:
        return subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def enable_in_repo(cwd):
    """Commit-able files so Codela works for everyone who opens the repo, everywhere.

    - .claude/settings.json: offers the Codela plugin to teammates on their own
      machines, and adds a SessionStart hook for cloud sessions (Claude Code on
      the web / desktop cloud), which don't load plugins.
    - .claude/codela/codela_lessons.py: the script that hook runs (stdlib only).
    - .claude/commands/codela-lessons.md: /codela-lessons for cloud sessions.
    Returns the paths written, or None if settings.json couldn't be read.
    """
    root = _toplevel(cwd)
    if not root:
        return None
    settings_path = os.path.join(root, ".claude", "settings.json")
    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except FileNotFoundError:
        settings = {}
    except Exception:
        return None  # don't rewrite a settings file we can't parse
    hook_cmd = f'python3 "$CLAUDE_PROJECT_DIR/{REPO_SCRIPT}" --cloud'
    settings.setdefault("extraKnownMarketplaces", {})["codela"] = {
        "source": {"source": "github", "repo": MARKETPLACE_REPO}}
    settings.setdefault("enabledPlugins", {})["codela@codela"] = True
    starts = settings.setdefault("hooks", {}).setdefault("SessionStart", [])
    if not any(h.get("command") == hook_cmd for g in starts for h in g.get("hooks", [])):
        starts.append({"hooks": [{"type": "command", "command": hook_cmd, "timeout": 30}]})
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    script_dst = os.path.join(root, REPO_SCRIPT)
    os.makedirs(os.path.dirname(script_dst), exist_ok=True)
    with open(os.path.abspath(__file__)) as src, open(script_dst, "w") as dst:
        dst.write(src.read())

    cmd_dst = os.path.join(root, REPO_COMMAND)
    os.makedirs(os.path.dirname(cmd_dst), exist_ok=True)
    with open(cmd_dst, "w") as f:
        f.write("---\ndescription: Show the production lessons Codela has learned for this repo\n"
                f"allowed-tools: Bash(python3 \"$CLAUDE_PROJECT_DIR/{REPO_SCRIPT}\":*)\n---\n\n"
                f'!`python3 "$CLAUDE_PROJECT_DIR/{REPO_SCRIPT}" --full || true`\n\n'
                "Summarize them for the user: one line per lesson saying what broke in production "
                "and what to do differently. If the user passed arguments, focus on: $ARGUMENTS\n")
    return [".claude/settings.json", REPO_SCRIPT, REPO_COMMAND]


def _done(res, repo):
    print(f"Codela is set up for {repo}"
          + (f" (service '{res['service']}')" if res.get("service") else "")
          + (f" in workspace '{res['workspace']}'" if res.get("workspace") else "") + ".")
    print("Your Codela key is saved in ~/.codela/credentials.json (not shown here). "
          "New Claude Code sessions in this repo will start with its production lessons.")
    written = None
    try:
        written = enable_in_repo(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    except Exception:
        pass
    if written:
        host = urllib.parse.urlparse(server_url()).hostname
        print("\nSo it works for everyone and everywhere (teammates, Claude desktop, Claude Code on the web), "
              "I added these files to the repo. Commit and push them:\n  " + "\n  ".join(written))
        print("\nFor Claude Code on the web (cloud sessions don't load plugins), also, once per cloud "
              "environment at claude.ai/code → environment settings:\n"
              "  1. Environment variable CODELA_API_KEY = your Codela key "
              "(usecodela.com/connect → More options).\n"
              f"  2. Network access → Custom → allow {host}.")


def setup():
    repo = detect_repo(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if not repo:
        print("Codela: this folder has no git remote, so I can't tell which repo it is. "
              "Run /codela:setup from inside a cloned GitHub repo.")
        return

    # 1. A browser setup may already be finished.
    pending = _read(PENDING)
    if pending.get("code") and pending.get("repo") == repo:
        res = claim_pending()
        if res and res.get("status") == "done":
            return _done(res, repo)
        if res and res.get("status") == "pending":
            print(f"Setup for {repo} is waiting for you in the browser:\n\n  {pending['url']}\n")
            return _wait(repo, pending["url"])

    # 2. Already linked?
    key = api_key()
    if key:
        status, ws = request("GET", "/api/workspace", key=key)
        if status == 200 and any(r.get("repo") == repo.lower() for r in ws.get("repos", [])):
            svc = next(r["service"] for r in ws["repos"] if r["repo"] == repo.lower())
            return _done({"service": svc, "workspace": ws.get("name")}, repo)
        if status == 401:
            key = ""  # saved key no longer valid: set up from scratch

    # 3. Start a new browser setup.
    status, s = request("POST", "/api/setup/sessions", {"repo": repo}, key=key or None)
    if status != 201:
        print(f"Codela: could not start setup ({s.get('error') or 'HTTP ' + str(status)}).")
        return
    _write_private(PENDING, {"code": s["code"], "poll_token": s["poll_token"], "url": s["url"],
                             "repo": repo, "server": server_url()})
    opened = False
    try:
        opened = webbrowser.open(s["url"])
    except Exception:
        pass
    print(f"{'Opened' if opened else 'Open'} this link to connect {repo} to Codela "
          f"(pick your observability tool, paste a read-only key, confirm the service):\n\n  {s['url']}\n")
    if s.get("user_code"):
        print(f"When the page asks for a code, type:  {s['user_code']}\n"
              "(It proves the browser is yours; the link alone can't connect anything.)\n")
    print("Keys go into that page, never into this chat.")
    _wait(repo, s["url"])


def _wait(repo, url):
    deadline = time.time() + SETUP_WAIT_S
    while time.time() < deadline:
        time.sleep(3)
        res = claim_pending()
        if res and res.get("status") == "done":
            print()
            return _done(res, repo)
        if res and res.get("status") == "expired":
            print("That setup link expired. Run /codela:setup again.")
            return
    print("Still waiting for the browser. When you've finished there, run /codela:setup or "
          "/codela:lessons (or start a new session) and Codela picks it up. The link works for 24 hours.")


if __name__ == "__main__":
    try:
        if "--setup" in sys.argv:
            setup()
        elif "--full" in sys.argv:
            full()
        else:
            hook(cloud="--cloud" in sys.argv)
    except Exception:
        # A memory plugin must never break the session it's attached to.
        pass
