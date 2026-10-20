#!/usr/bin/env python3
"""Self-test for check_spec.py: python3 test_check_spec.py"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from check_spec import check, hook  # noqa: E402

REQ = """# Requirements Document

## Introduction
x
## Glossary
- **Svc**: the service
## Requirements

### Requirement 1: A
**User Story:** As a dev, I want a, so that b
#### Acceptance Criteria
1. WHEN a request arrives, THE Svc SHALL answer
2. IF the input is invalid, THEN THE Svc SHALL return an error
"""
DESIGN = "".join(f"## {h}\nx\n" for h in
                 ["Overview", "Architecture", "Components and Interfaces", "Data Models",
                  "Correctness Properties\n### Property 1: p\n**Validates: Requirements 1.1**",
                  "Error Handling", "Testing Strategy"])
TASKS = """# Implementation Plan: a

## Tasks
- [ ] 1. Build
  - [ ] 1.1 Code
    - _Requirements: 1.1, 1.2_
  - [ ] 1.2 Write unit tests for Code
    - _Requirements: 1.1_
  - [ ]* 1.3 Property test
    - **Property 1: p**
    - **Validates: Requirements 1.1**
- [ ] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Task Dependency Graph
```json
{"waves": [{"id": 0, "tasks": ["1.1"]}, {"id": 1, "tasks": ["1.2"]}, {"id": 2, "tasks": ["1.3"]}]}
```
"""
BUGFIX = """# Bugfix Requirements Document

## Introduction
x
## Bug Analysis

### Current Behavior (Defect)
1.1 WHEN q is 0 THEN the system
    crashes
### Expected Behavior (Correct)
2.1 WHEN q is 0 THEN the system SHALL return N/A
### Unchanged Behavior (Regression Prevention)
3.1 WHEN q is 1 THEN the system SHALL CONTINUE TO compute
"""
BUG_DESIGN = "".join(f"## {h}\nx\n" for h in
                     ["Overview", "Glossary", "Bug Details", "Expected Behavior", "Hypothesized Root Cause",
                      "Correctness Properties\nProperty 1: Bug Condition\n**Validates: Requirements 2.1**\n"
                      "Property 2: Preservation\n**Validates: Requirements 3.1**",
                      "Fix Implementation", "Testing Strategy"])
BUG_TASKS = """# Implementation Plan

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - zero
  - _Requirements: 1.1_
- [ ] 2. Write preservation property tests
  - **Property 2: Preservation** - positive
  - _Requirements: 3.1_
- [ ] 3. Fix
  - [ ] 3.1 Guard
    - _Requirements: 2.1, 3.1_
- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
"""


def spec(root, spec_type, **files):
    d = Path(root) / ".kiro" / "specs" / "s"
    d.mkdir(parents=True)
    (d / ".config.kiro").write_text(json.dumps({"specId": "x", "workflowType": "requirements-first", "specType": spec_type}))
    for name, text in files.items():
        (d / name.replace("_", ".")).write_text(text)
    return d


class CheckSpec(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_valid_feature_and_bugfix(self):
        self.assertEqual(check(spec(self.tmp + "/f", "feature", requirements_md=REQ, design_md=DESIGN, tasks_md=TASKS))[0], [])
        self.assertEqual(check(spec(self.tmp + "/b", "bugfix", bugfix_md=BUGFIX, design_md=BUG_DESIGN, tasks_md=BUG_TASKS))[0], [])

    def test_partial_spec_only_checks_written_files(self):
        d = spec(self.tmp, "feature", requirements_md=REQ)
        self.assertEqual(check(d, full=False)[0], [])
        self.assertIn("missing design.md", check(d)[0])

    def test_design_first_design_before_requirements(self):
        d = spec(self.tmp, "feature", design_md=DESIGN.replace("**Validates: Requirements 1.1**", ""))
        (d / ".config.kiro").write_text(json.dumps({"specId": "x", "workflowType": "design-first", "specType": "feature"}))
        self.assertEqual(check(d, full=False)[0], [])

    def test_feature_errors(self):
        bad_req = REQ.replace("WHEN a request", "When a request").replace("**User Story:**", "")
        bad_tasks = TASKS.replace("- [ ] 1. Build", "- [ ]* 1. Build").replace("1.1, 1.2_", "1.1, 9.9_")
        errs = "\n".join(check(spec(self.tmp, "feature", requirements_md=bad_req,
                                    design_md=DESIGN.replace("## Data Models", "## Models"), tasks_md=bad_tasks))[0])
        for want in ("not an EARS criterion", "no '**User Story:**'", "missing section 'Data Models'",
                     "must not carry '*'", "unknown requirement 9.9"):
            self.assertIn(want, errs)

    def test_unit_tests_required(self):
        only_optional = TASKS.replace("- [ ] 1.2 Write unit tests", "- [ ]* 1.2 Write unit tests")
        errs, warns = check(spec(self.tmp, "feature", requirements_md=REQ, design_md=DESIGN, tasks_md=only_optional))
        self.assertIn("no required unit test task", "\n".join(errs))
        self.assertIn("task 1: no required unit test sub-task", "\n".join(warns))

    def test_bugfix_errors(self):
        errs = "\n".join(check(spec(self.tmp, "bugfix", bugfix_md=BUGFIX.replace("SHALL CONTINUE TO", "SHALL"),
                                    design_md=BUG_DESIGN, tasks_md=BUG_TASKS.replace("**Property 2: Preservation**", "")))[0])
        self.assertIn("SHALL CONTINUE TO", errs)
        self.assertIn("bugfix task 2 must be a top-level task", errs)

    def run_hook(self, path):
        payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(path)}})
        err = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(payload)), contextlib.redirect_stderr(err):
            return hook(), err.getvalue()

    def test_hook(self):
        good = spec(self.tmp + "/g", "feature", requirements_md=REQ)
        self.assertEqual(self.run_hook(good / "requirements.md")[0], 0)
        bad = spec(self.tmp + "/b", "feature", requirements_md=REQ.replace("THE Svc SHALL answer", "THE Svc answers"))
        code, stderr = self.run_hook(bad / "requirements.md")
        self.assertEqual(code, 2)
        self.assertIn("not an EARS criterion", stderr)
        self.assertEqual(self.run_hook(Path(self.tmp) / "main.go")[0], 0)


if __name__ == "__main__":
    unittest.main()
