#!/usr/bin/env python3
"""Check a Kiro spec dir against the structural rules in SKILL.md. Usage: check_spec.py <spec-dir>"""
import json
import re
import sys
from pathlib import Path

d = Path(sys.argv[1])
errs, warns = [], []

cfg = json.loads((d / ".config.kiro").read_text()) if (d / ".config.kiro").exists() else {}
if cfg.get("workflowType") not in ("requirements-first", "design-first"):
    errs.append(".config.kiro: workflowType must be requirements-first or design-first")
if cfg.get("specType") not in ("feature", "bugfix"):
    errs.append(".config.kiro: specType must be feature or bugfix")
req_file = d / ("bugfix.md" if cfg.get("specType") == "bugfix" else "requirements.md")
for f in (req_file, d / "design.md", d / "tasks.md"):
    if not f.exists():
        errs.append(f"missing {f.name}")
if errs:
    print("\n".join("ERROR " + e for e in errs))
    sys.exit(1)

# requirement ids
ids = set()
if cfg["specType"] == "bugfix":
    ids = set(re.findall(r"^(\d+\.\d+) WHEN ", req_file.read_text(), re.M))
else:
    cur = None
    for line in req_file.read_text().splitlines():
        m = re.match(r"### Requirement (\d+)", line)
        if m:
            cur = m.group(1)
        m = re.match(r"(\d+)\. ", line)
        if m and cur:
            ids.add(f"{cur}.{m.group(1)}")
if not ids:
    errs.append(f"{req_file.name}: no numbered requirement clauses found")

# tasks
text = (d / "tasks.md").read_text()
task_re = re.compile(r"^( *)- \[([ x~-])\](\*)? (\d+(?:\.\d+)*)\.? ", re.M)
tasks = [(len(m.group(1)), m.group(2), bool(m.group(3)), m.group(4)) for m in task_re.finditer(text)]
cited = set()
for line in text.splitlines():
    if line.strip().startswith("- _Requirements:"):
        for r in re.findall(r"\d+\.\d+", line):
            cited.add(r)
            if ids and r not in ids:
                errs.append(f"tasks.md cites unknown requirement {r}")
for indent, _, optional, tid in tasks:
    if "." not in tid and optional:
        errs.append(f"task {tid}: top-level task must not carry '*'")
    if indent > 2 or tid.count(".") > 1:
        errs.append(f"task {tid}: more than two levels")
for r in sorted(ids - cited):
    warns.append(f"requirement {r} is not cited by any task")

# dependency graph
m = re.search(r"## Task Dependency Graph\s+```json\s+(.*?)```", text, re.S)
if not m:
    if cfg["specType"] == "feature":  # Kiro's bugfix workflow writes no graph
        errs.append("tasks.md: missing '## Task Dependency Graph' json block")
else:
    try:
        waves = json.loads(m.group(1))["waves"]
    except (ValueError, KeyError, TypeError) as e:
        errs.append(f"graph: invalid json ({e})")
        waves = []
    if [w["id"] for w in waves] != list(range(len(waves))):
        errs.append("graph: wave ids must be contiguous from 0")
    seen = {}
    for w in waves:
        for t in w["tasks"]:
            if t in seen:
                errs.append(f"graph: task {t} appears twice")
            seen[t] = w["id"]
    leaf = {tid for _, st, _, tid in tasks if "." in tid and st != "x"}  # [-] and [~] are in progress
    for t in sorted(leaf - set(seen)):
        errs.append(f"graph: incomplete leaf task {t} is missing")
    for t in sorted(set(seen) - {tid for _, _, _, tid in tasks}):
        errs.append(f"graph: unknown task {t}")

for w in warns:
    print("WARN  " + w)
for e in errs:
    print("ERROR " + e)
print(f"{len(errs)} error(s), {len(warns)} warning(s)")
sys.exit(1 if errs else 0)
