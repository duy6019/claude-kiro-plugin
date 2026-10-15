#!/usr/bin/env python3
"""Summarize a `kiro-cli chat --output-format stream-json` log: session, tool calls, denials, final text.

kiro_watch.py <run.jsonl>   prints a few lines instead of the raw stream (diff bodies and message chunks dropped)
"""
import json
import sys


def summarize(lines):
    out = {"session": None, "context_pct": None, "calls": [], "status": None, "final": ""}
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        d = e.get("data", {})
        u = d.get("update", {})
        if e.get("type") == "metadata":
            out["session"] = d.get("sessionId", out["session"])
            out["context_pct"] = d.get("contextUsagePercentage", out["context_pct"])
        elif u.get("sessionUpdate") == "tool_call_update" and u.get("status"):
            raw = u.get("rawInput") or {}
            out["calls"].append({
                "status": u["status"],
                "kind": u.get("kind"),
                "target": raw.get("path") or raw.get("command") or u.get("title"),
                "reason": (u.get("_meta") or {}).get("kiro", {}).get("toolCallFailureReason"),
            })
        elif e.get("type") == "runFinished":
            out["status"] = d.get("status")
            out["final"] = d.get("finalText", "")
    return out


def main():
    s = summarize(open(sys.argv[1], encoding="utf-8"))
    pct = s["context_pct"]
    print(f"session={s['session']} run={s['status']} context={pct:.1f}%" if pct is not None else f"session={s['session']} run={s['status']}")
    for c in s["calls"]:
        flag = "" if c["status"] == "completed" else f"  <-- {c['reason'] or c['status']}"
        print(f"{c['status']:9} {c['kind'] or '':8} {c['target']}{flag}")
    denied = [c for c in s["calls"] if c["status"] != "completed"]
    print(f"{len(s['calls'])} tool calls, {len(denied)} not completed")
    print("final: " + s["final"][-1500:])


if __name__ == "__main__":
    main()
