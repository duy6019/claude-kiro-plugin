#!/usr/bin/env python3
"""Run one Kiro prompt over ACP and broker its permission requests.

kiro_acp.py --cwd <dir> --queue <dir> --prompt-file <file> [--scope <path or glob>...]
            [--allow-cmd <regex>...] [--load <session id>] [--ask-timeout <seconds>]

Kiro asks before every write and shell command (reads are free). Each request gets one tier:
  allow  writes inside --scope, read-only git, commands matching --allow-cmd (full match, no shell operators)
  flag   other writes inside --cwd, including create over a committed file: allowed, listed for Claude's review
  reject writes outside --cwd, git that changes history or remotes, recursive/forced rm, sudo, network and deploy tools
  ask    create over a file with uncommitted changes, and any other command: written to <queue>/req-<n>.json;
         the runner waits for <queue>/resp-<n>.json ({"allow": true|false, "reason": "..."}) and rejects after --ask-timeout
Only allow_once is ever sent: Kiro applies allow_always to the whole tool for the rest of the session.
<queue>/done.json holds the session id, stop reason (or error), tool calls, decisions and Kiro's final text.
"""
import argparse
import fnmatch
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

GIT_READ = [r"git status( --short)?", r"git diff( --stat| --name-only)?( HEAD)?( -- [^-=\s][^=\s]*( [^-=\s][^=\s]*)*)?",
            r"git show HEAD:[^-=\s][^=\s]*", r"git log --oneline( -n [0-9]+)?( -- [^-=\s][^=\s]*)?"]
DANGER_BIN = {"sudo", "curl", "wget", "scp", "ssh", "nc", "glab", "gh", "kubectl", "terraform", "docker", "helm"}
DANGER_GIT = {"push", "commit", "reset", "checkout", "restore", "clean", "rebase", "stash", "merge", "cherry-pick",
              "tag", "am", "apply", "worktree"}
SHELL_OPS = re.compile(r"[;&|`$<>\n]")


def dangerous(cmd):
    """True when any command in the line runs a dangerous program (checked at command position, not in paths)."""
    for seg in re.split(r"[;&|()`\n]+|\$\(", cmd):
        words = seg.split()
        while words and re.match(r"^\w+=", words[0]):  # VAR=value prefixes
            words.pop(0)
        if not words:
            continue
        prog = Path(words[0]).name
        if prog in DANGER_BIN:
            return True
        if prog == "rm" and any(re.match(r"^-\w*[rRf]", w) or w in ("--recursive", "--force") for w in words[1:]):
            return True
        if prog == "git" and DANGER_GIT & set(words[1:]):
            return True
    return False


def in_scope(p, cwd, scope):
    for s in scope:
        if any(c in s for c in "*?["):
            if fnmatch.fnmatch(str(p), str(cwd / s)):
                return True
        elif p.is_relative_to((cwd / s).resolve()):
            return True
    return False


def classify(raw, cwd, scope, allow_cmd, dirty=frozenset()):
    """Return (tier, reason) for a permission request's rawInput.

    Writes inside cwd are allowed: git can restore committed content, and Claude reviews them after the task.
    "flag" marks an allowed write Claude should look at. Only overwriting uncommitted work is asked about.
    """
    path, cmd = raw.get("path"), raw.get("command", "")
    if path:  # write tool: command is create / strReplace / insert / append
        p = (cwd / path).resolve()  # absolute paths stay as they are
        if not p.is_relative_to(cwd):
            return "reject", "write outside the working directory"
        if cmd == "create" and p.exists():
            if str(p) in dirty:
                return "ask", "create would overwrite uncommitted changes"
            return "flag", "create overwrites a committed file (recoverable from git)"
        if in_scope(p, cwd, scope):
            return "allow", "write inside task scope"
        return "flag", "write outside the predicted task scope"
    if cmd:
        if dangerous(cmd):
            return "reject", "command changes history, deletes, escalates or reaches the network"
        if not SHELL_OPS.search(cmd) and any(re.fullmatch(r, cmd) for r in GIT_READ + allow_cmd):
            return "allow", "allowed command"
        return "ask", "command not in the allow list"
    return "ask", "tool other than write or shell"


def dirty_files(cwd):
    """Absolute paths with uncommitted changes (modified, staged or untracked) when the run starts."""
    out = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all"], cwd=cwd,
                         capture_output=True, text=True).stdout
    entries, paths = out.split("\0"), set()
    i = 0
    while i < len(entries):
        e = entries[i]
        if len(e) > 3:
            paths.add(str((cwd / e[3:]).resolve()))
            if e[0] in "RC":  # renames and copies carry the old path as the next entry
                i += 1
        i += 1
    return paths


def paths_in(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "path" and isinstance(v, str):
                yield v
            else:
                yield from paths_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from paths_in(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwd", required=True); ap.add_argument("--queue", required=True)
    ap.add_argument("--prompt-file", required=True); ap.add_argument("--load")
    ap.add_argument("--scope", nargs="*", default=[]); ap.add_argument("--allow-cmd", nargs="*", default=[])
    ap.add_argument("--ask-timeout", type=int, default=1200)
    a = ap.parse_args()
    cwd, queue = Path(a.cwd).resolve(), Path(a.queue)
    queue.mkdir(parents=True, exist_ok=True)
    dirty = dirty_files(cwd)
    proc = subprocess.Popen(["kiro-cli", "acp"], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    lock, pending, nid, asked = threading.Lock(), {}, [0], [0]
    calls, decisions, chunks, read, inputs = [], [], [], set(), {}

    def finish(done, code):
        (queue / "done.json").write_text(json.dumps(done, indent=2))
        proc.terminate()
        print(f"session={done.get('session')} stop={done.get('stopReason')} error={done.get('error')} "
              f"calls={len(calls)} failed={sum(c['status'] == 'failed' for c in calls)}")
        for d in decisions:
            print(f"{d['decision']:6} {d['target']}  ({d['reason']})")
        print("final: " + done.get("final", "")[-1500:])
        sys.exit(code)

    def send(msg):
        with lock:
            proc.stdin.write(json.dumps(msg) + "\n"); proc.stdin.flush()

    def permission(msg):
        raw = msg["params"]["toolCall"].get("rawInput") or {}
        tier, reason = classify(raw, cwd, a.scope, a.allow_cmd, dirty)
        target = raw.get("path") or raw.get("command") or msg["params"]["toolCall"].get("title")
        if tier == "ask":
            with lock:
                asked[0] += 1; n = asked[0]
            detail = {k: (v[:2000] if isinstance(v, str) else v) for k, v in raw.items()}
            req = {"n": n, "target": target, "reason": reason, "purpose": raw.get("__tool_use_purpose"), "rawInput": detail}
            if raw.get("path"):
                req["read_before"] = str((cwd / raw["path"]).resolve()) in read
            (queue / f"req-{n}.json").write_text(json.dumps(req, indent=2))
            resp, deadline, tick = queue / f"resp-{n}.json", time.time() + a.ask_timeout, threading.Event()
            while not resp.exists() and time.time() < deadline:
                tick.wait(1)  # poll for Claude's answer file
            if resp.exists():
                r = json.loads(resp.read_text())
                tier, reason = ("allow" if r.get("allow") else "reject"), "decided: " + r.get("reason", "")
            else:
                tier, reason = "reject", f"no decision within {a.ask_timeout}s"
        decisions.append({"target": target, "decision": tier, "reason": reason, "purpose": raw.get("__tool_use_purpose")})
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"outcome": {"outcome": "selected",
                                                                     "optionId": "reject_once" if tier == "reject" else "allow_once"}}})

    def handle(line):
        try:
            msg = json.loads(line)
        except ValueError:
            return
        if "id" in msg and msg.get("method") == "session/request_permission":
            threading.Thread(target=permission, args=(msg,), daemon=True).start()
        elif "id" in msg and "method" in msg:
            send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported"}})
        elif "id" in msg and msg["id"] in pending:
            pending[msg["id"]][1] = msg; pending[msg["id"]][0].set()
        elif msg.get("method") == "session/update":
            u = msg["params"].get("update", {})
            if u.get("sessionUpdate") == "agent_message_chunk":
                chunks.append(u.get("content", {}).get("text", ""))
            elif u.get("sessionUpdate") == "tool_call":
                inputs[u.get("toolCallId")] = u.get("rawInput") or {}
            elif u.get("sessionUpdate") == "tool_call_update" and u.get("status") in ("completed", "failed"):
                raw = u.get("rawInput") or inputs.get(u.get("toolCallId"), {})  # replayed updates carry no rawInput
                if u["status"] == "completed" and not raw.get("command"):
                    read.update(str((cwd / p).resolve()) for p in paths_in(raw))
                elif u["status"] == "completed" and raw.get("path"):
                    dirty.add(str((cwd / raw["path"]).resolve()))  # Kiro's own uncommitted work now
                calls.append({"status": u["status"], "target": raw.get("path") or raw.get("command") or u.get("title")})

    def reader():
        with open(queue / "acp.jsonl", "a") as log:
            for line in proc.stdout:
                log.write(line); log.flush()
                handle(line)
        eof.set()  # Kiro exited

    eof = threading.Event()

    def call(method, params):
        with lock:
            nid[0] += 1; i = nid[0]
            pending[i] = [threading.Event(), None]
        send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        while not pending[i][0].wait(1):
            if eof.is_set():
                break
        r = pending[i][1] or {"error": "kiro-cli acp exited"}
        if "error" in r:
            finish({"session": None, "error": f"{method}: {r['error']}", "calls": calls, "decisions": decisions,
                    "final": "".join(chunks)}, 1)
        return r["result"]

    threading.Thread(target=reader, daemon=True).start()
    call("initialize", {"protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}})
    if a.load:
        call("session/load", {"sessionId": a.load, "cwd": str(cwd), "mcpServers": []})
        sid = a.load
    else:
        sid = call("session/new", {"cwd": str(cwd), "mcpServers": []})["sessionId"]
    chunks.clear(); calls.clear()  # drop history replayed by session/load; files read earlier still count as read
    result = call("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": Path(a.prompt_file).read_text()}]})
    finish({"session": sid, "stopReason": result.get("stopReason"), "calls": calls, "decisions": decisions,
            "final": "".join(chunks)}, 0)


if __name__ == "__main__":
    main()
