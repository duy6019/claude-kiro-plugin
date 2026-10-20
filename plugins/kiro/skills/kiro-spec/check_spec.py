#!/usr/bin/env python3
"""Check a Kiro spec dir against the rules in SKILL.md (taken from Kiro IDE's spec prompts).

check_spec.py <spec-dir>   full check: every spec file must exist
check_spec.py --hook       PostToolUse hook: reads the tool call on stdin, checks the files written so far,
                           exits 2 with the errors on stderr so Claude fixes them
"""
import json
import re
import sys
from pathlib import Path

SUPPORTED = {"feature", "bugfix"}
EARS_START = ("THE ", "WHEN ", "WHILE ", "IF ", "WHERE ", "FOR ALL ")
FEATURE_DESIGN = ["Overview", "Architecture", "Components and Interfaces", "Data Models", "Error Handling", "Testing Strategy"]
BUGFIX_DESIGN = ["Overview", "Glossary", "Bug Details", "Expected Behavior", "Hypothesized Root Cause",
                 "Correctness Properties", "Fix Implementation", "Testing Strategy"]
BUGFIX_SECTIONS = ["Current Behavior (Defect)", "Expected Behavior (Correct)", "Unchanged Behavior (Regression Prevention)"]
CHECKPOINT_TEXT = "Ensure all tests pass, ask the user if questions arise."
TASK_RE = re.compile(r"^( *)- \[([ x~-])\](\*)? (\d+(?:\.\d+)*)\.? (.*)$")


def numbered(body, num_re):
    """Numbered items whose text may wrap onto indented continuation lines, joined into one line."""
    return [(m.group(1), " ".join(m.group(2).split()))
            for m in re.finditer(rf"^({num_re}) (.+(?:\n[ \t]+\S.*)*)", body, re.M)]


def headings(text, level):
    return [m.group(1).strip() for m in re.finditer(rf"^{'#' * level} (?!#)(.+)$", text, re.M)]


def require_in_order(found, required, fname, errs, warns):
    present = [h for h in required if h in found]
    for h in required:
        if h not in found:
            errs.append(f"{fname}: missing section '{h}'")
    if present != sorted(present, key=found.index):
        warns.append(f"{fname}: sections out of order, expected {present}")


def check_requirements(text, errs, warns):
    ids = set()
    if not text.startswith("# Requirements Document"):
        errs.append("requirements.md: first line must be '# Requirements Document'")
    h2 = headings(text, 2)
    for h in ("Introduction", "Requirements"):
        if h not in h2:
            errs.append(f"requirements.md: missing section '{h}'")
    if "Glossary" not in h2:
        warns.append("requirements.md: no '## Glossary'; system names in criteria must be defined there")
    blocks = re.split(r"^### Requirement (\d+)\b.*$", text, flags=re.M)
    nums = blocks[1::2]
    if nums != [str(i) for i in range(1, len(nums) + 1)]:
        warns.append(f"requirements.md: requirements not numbered 1..n: {nums}")
    for num, body in zip(nums, blocks[2::2]):
        body = re.split(r"^## ", body, flags=re.M)[0]
        if "**User Story:**" not in body:
            errs.append(f"requirements.md: Requirement {num} has no '**User Story:**'")
        if "#### Acceptance Criteria" not in body:
            errs.append(f"requirements.md: Requirement {num} has no '#### Acceptance Criteria'")
        crit = numbered(body, r"\d+\.")
        if not crit:
            errs.append(f"requirements.md: Requirement {num} has no numbered criteria")
        for n, c in crit:
            n = n.rstrip(".")
            ids.add(f"{num}.{n}")
            check_ears(f"requirements.md {num}.{n}", c, errs)
    return ids


def check_ears(where, c, errs):
    if not c.startswith(EARS_START) or " SHALL" not in c:
        errs.append(f"{where}: not an EARS criterion (start with THE/WHEN/WHILE/IF/WHERE and contain SHALL): {c[:70]}")
        return
    if c.startswith("IF ") and "THEN" not in c:
        errs.append(f"{where}: 'IF' criterion needs ', THEN THE <system> SHALL'")
    prefix = c.split(" SHALL")[0]
    pos = [prefix.find(k) for k in ("WHERE ", "WHILE ") if k in prefix]
    cond = [prefix.find(k) for k in ("WHEN ", "IF ") if k in prefix]
    if cond:
        pos.append(min(cond))
    if pos != sorted(pos):
        errs.append(f"{where}: complex clause order must be WHERE, WHILE, WHEN/IF, THE, SHALL")


def check_bugfix(text, errs, warns):
    ids = set()
    if not text.startswith("# Bugfix Requirements Document"):
        errs.append("bugfix.md: first line must be '# Bugfix Requirements Document'")
    h2 = headings(text, 2)
    for h in ("Introduction", "Bug Analysis"):
        if h not in h2:
            errs.append(f"bugfix.md: missing section '{h}'")
    extra = [h for h in h2 if h not in ("Introduction", "Bug Analysis")]
    if extra:
        warns.append(f"bugfix.md: extra sections {extra}; technical detail belongs in design.md")
    require_in_order(headings(text, 3), BUGFIX_SECTIONS, "bugfix.md", errs, warns)
    parts = re.split(r"^### (.+)$", text, flags=re.M)
    counts = {}
    for title, body in zip(parts[1::2], parts[2::2]):
        if title.strip() not in BUGFIX_SECTIONS:
            continue
        sec = str(BUGFIX_SECTIONS.index(title.strip()) + 1)
        for cid, c in numbered(body, r"\d+\.\d+"):
            x = cid.split(".")[0]
            ids.add(cid)
            counts[sec] = counts.get(sec, 0) + 1
            if x != sec:
                errs.append(f"bugfix.md {cid}: clause under '{title.strip()}' must be numbered {sec}.y")
                continue
            if not c.startswith("WHEN ") or " THEN " not in c:
                errs.append(f"bugfix.md {cid}: must read 'WHEN <condition> THEN the system ...'")
                continue
            if "THEN the system" not in c:
                warns.append(f"bugfix.md {cid}: Kiro's pattern is 'THEN the system ...'")
            if sec == "2" and "SHALL" not in c:
                errs.append(f"bugfix.md {cid}: expected behavior needs 'THEN the system SHALL'")
            elif sec == "3" and "SHALL CONTINUE TO" not in c:
                errs.append(f"bugfix.md {cid}: unchanged behavior needs 'THEN the system SHALL CONTINUE TO'")
    if counts.get("1", 0) != counts.get("2", 0):
        warns.append(f"bugfix.md: {counts.get('1', 0)} current vs {counts.get('2', 0)} expected clauses; each defect needs a matching expected clause")
    return ids


def check_design(text, spec_type, workflow, ids, errs, warns):
    h2 = headings(text, 2)
    if spec_type == "bugfix":
        require_in_order(h2, BUGFIX_DESIGN, "design.md", errs, warns)
    elif workflow == "design-first":
        if "Overview" not in h2:
            errs.append("design.md: missing section 'Overview'")
    else:
        require_in_order(h2, FEATURE_DESIGN, "design.md", errs, warns)
    if "Correctness Properties" not in h2:
        return
    body = re.split(r"^## Correctness Properties.*$", text, flags=re.M)[1]
    body = re.split(r"^## ", body, flags=re.M)[0]
    props = re.split(r"^.{0,8}Property (\d+)\b", body, flags=re.M)
    if spec_type == "bugfix" and props[1::2] != ["1", "2"]:
        errs.append("design.md: bugfix Correctness Properties must be exactly Property 1 (Bug Condition) and Property 2 (Preservation)")
    for num, pbody in zip(props[1::2], props[2::2]):
        m = re.search(r"Validates: Requirements ([\d., ]+)", pbody)
        if not m and not ids:
            continue  # design-first: properties are mapped to requirements after requirements exist
        if not m:
            errs.append(f"design.md: Property {num} has no 'Validates: Requirements X.Y'")
            continue
        for r in re.findall(r"\d+\.\d+", m.group(1)):
            if ids and r not in ids:
                errs.append(f"design.md: Property {num} validates unknown requirement {r}")


def parse_tasks(text):
    tasks, cur = [], None
    for line in text.splitlines():
        m = TASK_RE.match(line)
        if m:
            cur = {"indent": len(m.group(1)), "state": m.group(2), "opt": bool(m.group(3)),
                   "id": m.group(4), "title": m.group(5), "body": ""}
            tasks.append(cur)
        elif cur is not None:
            if line.startswith("#"):
                cur = None
            else:
                cur["body"] += line + "\n"
    return tasks


def check_tasks(text, spec_type, ids, full, errs, warns):
    if not text.startswith("# Implementation Plan"):
        errs.append("tasks.md: first line must start with '# Implementation Plan'")
    tasks = parse_tasks(text)
    if not tasks:
        errs.append("tasks.md: no checkbox tasks found")
        return
    cited = set()
    for t in tasks:
        tid = t["id"]
        if "." not in tid and t["opt"]:
            errs.append(f"tasks.md task {tid}: top-level task must not carry '*'")
        if t["indent"] > 2 or tid.count(".") > 1:
            errs.append(f"tasks.md task {tid}: more than two levels")
        for line in t["body"].splitlines():
            if line.strip().startswith("- _Requirements:"):
                for r in re.findall(r"\d+\.\d+", line):
                    cited.add(r)
                    if ids and r not in ids:
                        errs.append(f"tasks.md task {tid} cites unknown requirement {r}")
        if t["title"].lower().startswith(("checkpoint", "final checkpoint")) and CHECKPOINT_TEXT not in t["body"]:
            warns.append(f"tasks.md task {tid}: checkpoint text should be '{CHECKPOINT_TEXT}'")
        if spec_type == "feature" and re.search(r"\*\*Property \d+", t["body"]) and "**Validates: Requirements" not in t["body"]:
            errs.append(f"tasks.md task {tid}: property task needs '**Validates: Requirements X.Y**'")
    if full:
        for r in sorted(ids - cited):
            warns.append(f"requirement {r} is not cited by any task")

    def checkpoint(t):
        return t["title"].lower().startswith(("checkpoint", "final checkpoint"))

    def required_test(t):
        return "test" in t["title"].lower() and not t["opt"] and not checkpoint(t)

    if not any(required_test(t) for t in tasks):
        errs.append("tasks.md: no required unit test task; every spec needs unit tests that are not marked [ ]*")
    if spec_type == "feature":
        for t in tasks:
            if "." in t["id"] or checkpoint(t):
                continue
            subs = [s for s in tasks if s["id"].startswith(t["id"] + ".")]
            if subs and not any(required_test(s) for s in subs):
                warns.append(f"tasks.md task {t['id']}: no required unit test sub-task")

    top = [t for t in tasks if "." not in t["id"]]
    if spec_type == "bugfix":
        need = [("1", "**Property 1: Bug Condition**"), ("2", "**Property 2: Preservation**")]
        for tid, marker in need:
            t = next((t for t in top if t["id"] == tid), None)
            if t is None or marker not in t["body"]:
                errs.append(f"tasks.md: bugfix task {tid} must be a top-level task containing '{marker}'")
        if not top[-1]["title"].lower().startswith("checkpoint"):
            warns.append("tasks.md: bugfix plan should end with a Checkpoint task")
    elif "Tasks" not in headings(text, 2):
        errs.append("tasks.md: missing section '## Tasks'")

    m = re.search(r"## Task Dependency Graph\s+```json\s+(.*?)```", text, re.S)
    if not m:
        if spec_type == "feature":
            errs.append("tasks.md: missing '## Task Dependency Graph' json block")
        return
    try:
        waves = json.loads(m.group(1))["waves"]
    except (ValueError, KeyError, TypeError) as e:
        errs.append(f"graph: invalid json ({e})")
        return
    if [w.get("id") for w in waves] != list(range(len(waves))):
        errs.append("graph: wave ids must be contiguous from 0")
    seen = {}
    for w in waves:
        for t in w.get("tasks", []):
            if t in seen:
                errs.append(f"graph: task {t} appears twice")
            seen[t] = w.get("id")
    all_ids = {t["id"] for t in tasks}
    leaf = {t["id"] for t in tasks if "." in t["id"] and t["state"] != "x"}  # [-] and [~] are in progress
    for t in sorted(leaf - set(seen)):
        errs.append(f"graph: incomplete leaf task {t} is missing")
    for t in sorted(set(seen) - all_ids):
        errs.append(f"graph: unknown task {t}")


def check(d, full=True):
    errs, warns = [], []
    cfg_file = d / ".config.kiro"
    cfg = {}
    if cfg_file.exists():
        try:
            cfg = json.loads(cfg_file.read_text())
        except ValueError as e:
            errs.append(f".config.kiro: invalid json ({e})")
    elif full:
        errs.append("missing .config.kiro")
    spec_type = cfg.get("specType") or ("bugfix" if (d / "bugfix.md").exists() else "feature")
    workflow = cfg.get("workflowType", "requirements-first")
    if spec_type not in SUPPORTED:
        warns.append(f"specType '{spec_type}' is not covered by this checker; nothing checked")
        return errs, warns
    if cfg and workflow not in ("requirements-first", "design-first") and spec_type == "feature":
        errs.append(".config.kiro: workflowType must be requirements-first or design-first")
    if cfg and not cfg.get("specId"):
        errs.append(".config.kiro: missing specId")

    req_name = "bugfix.md" if spec_type == "bugfix" else "requirements.md"
    files = {n: d / n for n in (req_name, "design.md", "tasks.md")}
    if full:
        errs += [f"missing {n}" for n, f in files.items() if not f.exists()]
    ids = set()
    if files[req_name].exists():
        text = files[req_name].read_text()
        ids = check_bugfix(text, errs, warns) if spec_type == "bugfix" else check_requirements(text, errs, warns)
    if files["design.md"].exists():
        check_design(files["design.md"].read_text(), spec_type, workflow, ids, errs, warns)
    if files["tasks.md"].exists():
        check_tasks(files["tasks.md"].read_text(), spec_type, ids, full, errs, warns)
    return errs, warns


def hook():
    try:
        call = json.load(sys.stdin)
        path = Path(call.get("tool_input", {}).get("file_path", ""))
    except (ValueError, AttributeError):
        return 0
    if "/.kiro/specs/" not in path.as_posix() or path.name not in ("requirements.md", "bugfix.md", "design.md", "tasks.md", ".config.kiro"):
        return 0
    errs, _ = check(path.parent, full=False)
    if not errs:
        return 0
    print(f"Kiro spec check failed for {path.parent}. Fix these before continuing:", file=sys.stderr)
    print("\n".join("- " + e for e in errs), file=sys.stderr)
    return 2


def main():
    if sys.argv[1:] == ["--hook"]:
        sys.exit(hook())
    errs, warns = check(Path(sys.argv[1]))
    for w in warns:
        print("WARN  " + w)
    for e in errs:
        print("ERROR " + e)
    print(f"{len(errs)} error(s), {len(warns)} warning(s)")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
