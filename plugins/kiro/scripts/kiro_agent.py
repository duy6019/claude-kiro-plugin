#!/usr/bin/env python3
"""Create or delete a task-scoped Kiro agent in ~/.kiro/agents (kept out of the repo's git status).

kiro_agent.py create <name> --write <abs-glob>... --pkg <./go/pkg>...
kiro_agent.py delete <name>

Kiro full-matches shell allowedCommands and rejects chained commands (&&, ;, |, $()),
so each package gets exact go test / go vet / gofmt patterns.
"""
import argparse
import json
import re
import sys
from pathlib import Path

AGENTS = Path.home() / ".kiro" / "agents"
PREFIX = "claude-kiro-"
PKG_RE = re.compile(r"^\./[A-Za-z0-9_./-]*$")


def esc(s):
    return s.replace(".", r"\.")  # package paths are validated, so '.' is the only regex metachar left


def commands(pkgs):
    cmds = []
    for p in pkgs:
        if not PKG_RE.match(p) or ".." in p.replace("/...", ""):
            sys.exit(f"invalid package path: {p}")
        d = p.rstrip("/").removesuffix("/...").removeprefix("./")  # e.g. pkg/x, or "" for the module root
        pkg = f"./{d}" if d else "."
        cmds += [rf"go test {esc(pkg)}/\.\.\. -timeout 300s( -v)?( -run \S+)?( -count=1)?",
                 rf"go vet {esc(pkg)}/\.\.\.",
                 rf"gofmt -l {esc(d or '.')}"]
    return cmds


def create(name, write, pkgs):
    for w in write:
        if not w.startswith("/"):
            sys.exit(f"--write must be an absolute path or glob: {w}")
    agent = {
        "name": name,
        "description": "Task-scoped agent created by the Claude Code kiro plugin",
        "tools": ["read", "write", "shell", "glob", "grep"],
        "allowedTools": ["read", "glob", "grep"],
        "toolsSettings": {
            "write": {"allowedPaths": write},
            "shell": {"allowedCommands": commands(pkgs), "denyByDefault": True},
        },
    }
    AGENTS.mkdir(parents=True, exist_ok=True)
    path = AGENTS / f"{name}.json"
    path.write_text(json.dumps(agent, indent=2))
    print(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["create", "delete"])
    ap.add_argument("name")
    ap.add_argument("--write", nargs="*", default=[])
    ap.add_argument("--pkg", nargs="*", default=[])
    a = ap.parse_args()
    if not a.name.startswith(PREFIX):
        sys.exit(f"agent name must start with {PREFIX}")  # never touch the user's own agents
    if a.action == "create":
        create(a.name, a.write, a.pkg)
    else:
        (AGENTS / f"{a.name}.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
