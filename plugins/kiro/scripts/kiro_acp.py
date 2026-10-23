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
With --sandbox (auto: on when bwrap can start) Kiro runs in kiro_sandbox.sh: read-only filesystem except --cwd,
no credentials, no user sockets. Every other command is then allowed and flagged; database clients are still asked.
Only allow_once is ever sent: Kiro applies allow_always to the whole tool for the rest of the session.
<queue>/done.json holds the session id, stop reason (or error), tool calls, decisions and Kiro's final text.
"""
import argparse
import fnmatch
import json
import os
import re
import shlex
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
DB_CLIENTS = {"psql", "mysql", "redis-cli", "mongosh", "mongo", "clickhouse", "clickhouse-client", "sqlcmd", "cqlsh"}
SAFE_FILTERS = [r"echo( [^;&|`$<>]*)?", r"(tail|head)( -n ?[0-9]+| -[0-9]+)?", r"grep( -[A-Za-z]+)* \S+", r"wc( -[lwc])?"]


def segments(cmd):
    """Split a command line on unquoted |, ;, && and ||; quotes are honoured (go test -run 'A|B')."""
    lex = shlex.shlex(cmd, posix=True, punctuation_chars="|;&")
    lex.whitespace_split = True
    out, cur = [], []
    for tok in lex:
        if tok in ("|", ";", "&&", "||"):
            out.append(" ".join(cur)); cur = []
        else:
            cur.append(tok)
    return out + [" ".join(cur)]


def safe_pipeline(cmd, allow_cmd):
    """Allowed commands joined by |, ;, && or ||, plus output filters (echo, tail, head, grep, wc).
    Redirection, subshells and anything else still go to Claude."""
    cmd = cmd.replace(" 2>&1", "")
    if re.search(r"[`$<>\n]", cmd):
        return False
    try:
        parts = segments(cmd)
    except ValueError:  # unbalanced quotes
        return False
    return all(p and any(re.fullmatch(r, p) for r in GIT_READ + allow_cmd + SAFE_FILTERS) for p in parts)


def commands_in(cmd):
    """Word lists of every command in the line (checked at command position, not inside paths)."""
    for seg in re.split(r"[;&|()`\n]+|\$\(", cmd):
        words = seg.split()
        while words and re.match(r"^\w+=", words[0]):  # VAR=value prefixes
            words.pop(0)
        if words:
            yield Path(words[0]).name, words


def uses_database(cmd):
    return any(prog in DB_CLIENTS for prog, _ in commands_in(cmd))


def dangerous(cmd):
    """True when any command in the line changes history or remotes, force-deletes, escalates or reaches the network."""
    for prog, words in commands_in(cmd):
        if prog in DANGER_BIN:
            return True
        if prog == "rm" and any(re.match(r"^-\w*[rRf]", w) or w in ("--recursive", "--force") for w in words[1:]):
            return True
        if prog == "git" and DANGER_GIT & set(words[1:]):
            return True
        if prog == "go" and any(w.split("=")[0] in ("-exec", "-toolexec") for w in words[1:]):
            return True  # runs an arbitrary program
    return False


def in_scope(p, cwd, scope):
    for s in scope:
        if any(c in s for c in "*?["):
            if fnmatch.fnmatch(str(p), str(cwd / s)):
                return True
        elif p.is_relative_to((cwd / s).resolve()):
            return True
    return False


def classify(raw, cwd, scope, allow_cmd, dirty=frozenset(), sandbox=False, saved=False, own=frozenset()):
    """Return (tier, reason) for a permission request's rawInput.

    Writes inside cwd are allowed: git can restore committed content, and Claude reviews them after the task.
    "flag" marks an allowed action Claude should look at. Only overwriting uncommitted work is asked about.
    In the sandbox other commands are allowed and flagged, since they cannot write outside cwd or use credentials.
    """
    path, cmd = raw.get("path"), raw.get("command", "")
    if "operations" in raw:  # read tool: Kiro asks only for files outside its workspace
        if sandbox:
            return "allow", "read (credentials are hidden in the sandbox)"
        return "ask", "read outside the working directory"
    if path:  # write tool: command is create / strReplace / insert / append
        p = (cwd / path).resolve()  # absolute paths stay as they are
        if not p.is_relative_to(cwd):
            return "reject", "write outside the working directory"
        if cmd == "create" and p.exists():
            if str(p) in own:
                return "flag", "create overwrites a file Kiro wrote in this run"
            if str(p) in dirty:
                if saved:
                    return "flag", "create overwrites uncommitted changes (saved in snapshot.patch)"
                return "ask", "create would overwrite uncommitted changes"
            return "flag", "create overwrites a committed file (recoverable from git)"
        if in_scope(p, cwd, scope):
            return "allow", "write inside task scope"
        return "flag", "write outside the predicted task scope"
    if cmd:
        if dangerous(cmd):
            return "reject", "command changes history, deletes, escalates or reaches the network"
        if uses_database(cmd):
            return "ask", "database client"
        if safe_pipeline(cmd, allow_cmd):
            return "allow", "allowed command"
        if sandbox:
            return "flag", "command allowed inside the sandbox"
        return "ask", "command not in the allow list"
    return "ask", "tool other than write or shell"


SANDBOX_SH = Path(__file__).with_name("kiro_sandbox.sh")


def sandbox_works():
    """bwrap can start here (it fails inside some other sandboxes, where nested user namespaces are not allowed)."""
    try:
        return subprocess.run(["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "true"],
                              capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


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


def snapshot(cwd, out):
    """Save every uncommitted change (untracked files too) as a patch, using a temporary index so the
    real index and working tree are untouched. Returns True when the patch was written."""
    env = {**os.environ, "GIT_INDEX_FILE": str(out.with_suffix(".index"))}
    try:
        subprocess.run(["git", "read-tree", "HEAD"], cwd=cwd, env=env, check=True, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=cwd, env=env, check=True, capture_output=True)
        diff = subprocess.run(["git", "diff", "--cached", "--binary", "HEAD"], cwd=cwd, env=env, check=True,
                              capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return False
    out.write_bytes(diff)
    return True


def rule_matches(rules, raw, cwd):
    """Rules Claude asked to remember: "write:<glob relative to cwd>" or "cmd:<full-match regex>"."""
    for r in rules:
        kind, _, pat = r.partition(":")
        if kind == "write" and raw.get("path") and fnmatch.fnmatch(str((cwd / raw["path"]).resolve()), str(cwd / pat)):
            return r
        if kind == "cmd" and raw.get("command") and not raw.get("path") and re.fullmatch(pat, raw["command"]):
            return r
    return None


def next_event(queue, timeout):
    """For a polling driver: wait for the next unanswered request or the end of the run, print it, exit."""
    queue, tick, deadline = Path(queue), threading.Event(), time.time() + timeout
    while time.time() < deadline:
        for req in sorted(queue.glob("req-*.json"), key=lambda p: int(p.stem.split("-")[1])):
            if not (queue / req.name.replace("req-", "resp-")).exists():
                print(req.read_text())
                return
        done = queue / "done.json"
        if done.exists():
            d = json.loads(done.read_text())
            print(f"ERROR {d['error']}" if d.get("error") else f"DONE session={d['session']}")
            return
        tick.wait(1)
    print("RUNNING")


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


def watch(queue):
    """For a Monitor: one line per request waiting for Claude, then DONE or ERROR once done.json exists."""
    queue, seen, tick = Path(queue), set(), threading.Event()
    while True:
        for req in sorted(queue.glob("req-*.json")):
            if req.name not in seen:
                seen.add(req.name)
                r = json.loads(req.read_text())
                print(f"ASK {r['n']}: {r['reason']} | {r['target']} | read_before={r.get('read_before')} | {r.get('purpose')}", flush=True)
        done = queue / "done.json"
        if done.exists():
            d = json.loads(done.read_text())
            print(f"ERROR {d['error']}" if d.get("error") else f"DONE session={d['session']}", flush=True)
            return
        tick.wait(1)


def main():
    if sys.argv[1:2] == ["--watch"]:
        return watch(sys.argv[2])
    if sys.argv[1:2] == ["--next"]:
        return next_event(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 540)
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwd", required=True); ap.add_argument("--queue", required=True)
    ap.add_argument("--prompt-file", required=True); ap.add_argument("--load")
    ap.add_argument("--scope", nargs="*", default=[]); ap.add_argument("--allow-cmd", nargs="*", default=[])
    ap.add_argument("--ask-timeout", type=int, default=1200)
    ap.add_argument("--sandbox", choices=["auto", "on", "off"], default="auto")
    ap.add_argument("--model", default="", help="Kiro model id (kiro-cli chat --list-models); empty = Kiro's default")
    ap.add_argument("--effort", choices=["", "low", "medium", "high", "xhigh", "max"], default="")
    a = ap.parse_args()
    cwd, queue = Path(a.cwd).resolve(), Path(a.queue).resolve()
    queue.mkdir(parents=True, exist_ok=True)
    dirty = dirty_files(cwd)
    saved = bool(dirty) and snapshot(cwd, queue / "snapshot.patch")
    if dirty and not saved:
        print("snapshot: failed, overwriting uncommitted changes will be asked", flush=True)
    sandbox = a.sandbox != "off" and sandbox_works()
    if a.sandbox == "on" and not sandbox:
        sys.exit("--sandbox on, but bwrap cannot start here (for example inside another sandbox)")
    if not sandbox:
        print("sandbox: off, using permission tiers only", flush=True)
    pipes = {"cwd": cwd, "stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL,
             "text": True, "bufsize": 1}
    env = {**os.environ, "KIRO_SANDBOX_SH": str(SANDBOX_SH), "KIRO_MODEL": a.model, "KIRO_EFFORT": a.effort}
    if sandbox:
        proc = subprocess.Popen(["bash", "-c", 'exec bash "$KIRO_SANDBOX_SH"'], env=env, **pipes)
    else:
        proc = subprocess.Popen(["bash", "-c", 'exec kiro-cli acp ${KIRO_MODEL:+--model "$KIRO_MODEL"} '
                                 '${KIRO_EFFORT:+--effort "$KIRO_EFFORT"}'], env=env, **pipes)
    lock, pending, nid, asked = threading.Lock(), {}, [0], [0]
    calls, decisions, chunks, read, inputs, own, rules = [], [], [], set(), {}, set(), []
    used_model = [a.model or "default"]

    def finish(done, code):
        done["sandbox"] = sandbox
        done["model"], done["effort"] = used_model[0], a.effort or "default"  # model as Kiro reported it
        done["snapshot"] = str(queue / "snapshot.patch") if saved else None
        done["rules"] = rules
        (queue / "done.json").write_text(json.dumps(done, indent=2))
        proc.terminate()
        print(f"session={done.get('session')} model={done['model']} effort={done['effort']} sandbox={sandbox} stop={done.get('stopReason')} error={done.get('error')} "
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
        tier, reason = classify(raw, cwd, a.scope, a.allow_cmd, dirty, sandbox, saved, own)
        target = raw.get("path") or raw.get("command") or msg["params"]["toolCall"].get("title")
        rule = rule_matches(rules, raw, cwd) if tier == "ask" else None
        if rule:
            tier, reason = "flag", f"remembered rule {rule}"
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
                remember = r.get("remember") or []
                if r.get("allow"):
                    rules.extend([remember] if isinstance(remember, str) else remember)
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
                    own.add(str((cwd / raw["path"]).resolve()))
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
        session = call("session/load", {"sessionId": a.load, "cwd": str(cwd), "mcpServers": []}) or {}
        sid = a.load
    else:
        session = call("session/new", {"cwd": str(cwd), "mcpServers": []})
        sid = session["sessionId"]
    used_model[0] = (session.get("models") or {}).get("currentModelId") or a.model or "default"
    chunks.clear(); calls.clear()  # drop history replayed by session/load; files read earlier still count as read
    result = call("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": Path(a.prompt_file).read_text()}]})
    finish({"session": sid, "stopReason": result.get("stopReason"), "calls": calls, "decisions": decisions,
            "final": "".join(chunks)}, 0)


if __name__ == "__main__":
    main()
