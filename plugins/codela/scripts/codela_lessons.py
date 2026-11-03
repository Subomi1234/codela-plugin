#!/usr/bin/env python3
"""Fetch this repo's production lessons from Codela.

  --hook   SessionStart hook: reads the hook JSON on stdin, prints the lessons
           as additionalContext so they are in the agent's context from the
           first turn. Never fails the session: if Codela is unreachable it
           uses the last cached copy, or prints nothing.
  --full   Print every lesson in full (used by the /codela:lessons command).
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


def api_key():
    return (os.environ.get("CODELA_API_KEY")
            or os.environ.get("CLAUDE_PLUGIN_OPTION_API_KEY")
            or _read(CREDS).get(server_url(), {}).get("api_key") or "").strip()


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
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
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
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
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


def hook():
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
    context, note = "", ""
    try:
        data = fetch(repo, "context")
        context = data.get("context") or ""
        if cache:
            with open(cache, "w") as f:
                json.dump(data, f)
    except Exception:
        if cache and os.path.exists(cache):
            with open(cache) as f:
                context = json.load(f).get("context") or ""
            note = "\n\n(Codela was unreachable; these are the last cached lessons.)"
    if context:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context + note,
        }}))


def full():
    repo = detect_repo(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if not repo:
        print("Codela: could not determine this repo (no git remote). "
              "Set the plugin's `repo` option to owner/name.")
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
    print(f"Codela — {len(lessons)} production lesson(s) for {repo}\n")
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


def _done(res, repo):
    print(f"Codela is set up for {repo}"
          + (f" (service '{res['service']}')" if res.get("service") else "")
          + (f" in workspace '{res['workspace']}'" if res.get("workspace") else "") + ".")
    print("Your Codela key is saved in ~/.codela/credentials.json (not shown here). "
          "New Claude Code sessions in this repo will start with its production lessons.")


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
    print("Still waiting for the browser. When you've finished there, run /codela:setup again "
          "(or just start a new session — Codela picks it up automatically). The link works for 30 minutes.")


if __name__ == "__main__":
    try:
        if "--setup" in sys.argv:
            setup()
        elif "--full" in sys.argv:
            full()
        else:
            hook()
    except Exception:
        # A memory plugin must never break the session it's attached to.
        pass
