#!/usr/bin/env python3
"""Self-test for the permission tiers in kiro_acp.py: python3 test_kiro_acp.py"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kiro_acp import classify, dirty_files, next_event, rule_matches, snapshot, watch  # noqa: E402

CHECKS = [r"go test \./[\w./-]* -timeout 300s", r"npm test"]


class Classify(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp()).resolve()
        (self.cwd / "pkg" / "x").mkdir(parents=True)
        (self.cwd / "pkg" / "x" / "x.go").write_text("package x\n")
        self.scope = [str(self.cwd / "pkg" / "x"), str(self.cwd / "spec" / "tasks.md"), str(self.cwd / "pkg" / "y" / "*_test.go")]

    def tier(self, dirty=frozenset(), **raw):
        return classify(raw, self.cwd, self.scope, CHECKS, dirty)[0]

    def test_writes(self):
        x = self.cwd / "pkg/x/x.go"
        self.assertEqual(self.tier(path=str(self.cwd / "pkg/x/new.go"), command="create"), "allow")
        self.assertEqual(self.tier(path=str(x), command="strReplace"), "allow")
        self.assertEqual(self.tier(path=str(x), command="create"), "flag")  # committed file, recoverable
        self.assertEqual(self.tier(dirty={str(x)}, path=str(x), command="create"), "ask")  # uncommitted work
        self.assertEqual(self.tier(path=str(self.cwd / "spec/tasks.md"), command="strReplace"), "allow")
        self.assertEqual(self.tier(path=str(self.cwd / "pkg/y/y_test.go"), command="create"), "allow")
        self.assertEqual(self.tier(path=str(self.cwd / "pkg/y/y.go"), command="strReplace"), "flag")
        self.assertEqual(self.tier(path=str(self.cwd / "pkg/xy/z.go"), command="create"), "flag")  # prefix is not a parent
        self.assertEqual(self.tier(path="/etc/passwd", command="strReplace"), "reject")
        self.assertEqual(self.tier(path=str(self.cwd / "pkg/x/../../../escape.go"), command="create"), "reject")
        self.assertEqual(self.tier(path="pkg/x/rel.go", command="create"), "allow")  # relative to cwd, not the runner
        self.assertEqual(self.tier(path="../outside.go", command="create"), "reject")

    def test_commands(self):
        for c in ("git status --short", "git diff -- pkg/x/x.go", "git show HEAD:pkg/x/x.go",
                  "go test ./pkg/x/... -timeout 300s", "npm test"):
            self.assertEqual(self.tier(command=c), "allow", c)
        for c in ("git push origin main", "git commit -am x", "git -C . push", "git checkout -- pkg", "rm -rf build",
                  "sudo ls", "curl https://example.com", "FOO=1 gh pr list", "go test ./... -timeout 300s && git push"):
            self.assertEqual(self.tier(command=c), "reject", c)
        self.assertEqual(self.tier(command="go test ./pkg/gh/... -timeout 300s"), "allow")  # 'gh' in a path is fine
        self.assertEqual(self.tier(command="rm pkg/x/tmp.txt"), "ask")
        for c in ("go test ./pkg/x/... -timeout 300s 2>&1 | tail -20", "go test ./pkg/x/... -timeout 300s; echo EXIT",
                  "npm test && git status --short", "go test ./pkg/x/... -timeout 300s | grep -v ok"):
            self.assertEqual(self.tier(command=c), "allow", c)
        for c in ("go test ./pkg/x/... -timeout 300s > out.txt", "echo $(cat x)", "git diff --output=x", "make generate",
                  "go test ./... -timeout 900s", "go test ./pkg/x/... -timeout 300s | sh", "sed -i s/a/b/ tasks.md",
                  "cd pkg && go test . -timeout 300s"):
            self.assertEqual(self.tier(command=c), "ask", c)

    def test_go_preset_from_run_md(self):
        go = [r"go test( \S+)* -timeout (300|[12][0-9]{2}|[1-9][0-9]?)s( \S+)*", r"go vet( \S+)+"]
        tier = lambda c: classify({"command": c}, self.cwd, self.scope, go)[0]  # noqa: E731
        for c in ("go test -race -timeout 300s -run 'TestA|TestB' ./modules/enforcement/offtrip/... 2>&1 | tail -40",
                  "go test ./... -timeout 120s -count=1", "go vet ./... && echo ok"):
            self.assertEqual(tier(c), "allow", c)
        for c in ("go test ./... -timeout 600s", "go test ./...", "go test 'unbalanced ./..."):
            self.assertEqual(tier(c), "ask", c)
        for c in ("go test -exec sh -timeout 300s ./...", "go test -toolexec=x -timeout 300s ./..."):
            self.assertEqual(tier(c), "reject", c)

    def test_sandbox_allows_other_commands(self):
        tier = lambda c: classify({"command": c}, self.cwd, self.scope, CHECKS, sandbox=True)[0]  # noqa: E731
        for c in ("make generate", "go env GOCACHE > env.txt", "sqlc version 2>/dev/null; which sqlc"):
            self.assertEqual(tier(c), "flag", c)
        for c in ("git reset --hard", "git clean -fd", "rm -rf build", "curl https://example.com"):
            self.assertEqual(tier(c), "reject", c)
        for c in ("psql -h db -c 'select 1'", "go test ./... -timeout 300s && redis-cli ping"):
            self.assertEqual(tier(c), "ask", c)
        self.assertEqual(classify({"command": "make generate"}, self.cwd, self.scope, CHECKS)[0], "ask")  # no sandbox
        read = {"operations": [{"mode": "Line", "path": "/opt/plugin/FORMAT.md"}]}
        self.assertEqual(classify(read, self.cwd, self.scope, CHECKS, sandbox=True)[0], "allow")
        self.assertEqual(classify(read, self.cwd, self.scope, CHECKS)[0], "ask")

    def test_other_tools_ask(self):
        self.assertEqual(self.tier(url="https://example.com"), "ask")

    def test_watch_lists_requests_then_done(self):
        q = self.cwd / "q"
        q.mkdir()
        (q / "req-1.json").write_text(json.dumps({"n": 1, "reason": "r", "target": "t", "purpose": "p"}))
        (q / "done.json").write_text(json.dumps({"session": "s1"}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            watch(q)
        self.assertEqual(out.getvalue().splitlines(), ["ASK 1: r | t | read_before=None | p", "DONE session=s1"])

    def test_overwrite_tiers_with_snapshot_and_own_writes(self):
        x = str(self.cwd / "pkg/x/x.go")
        raw = {"path": x, "command": "create"}
        self.assertEqual(classify(raw, self.cwd, self.scope, CHECKS, dirty={x})[0], "ask")
        self.assertEqual(classify(raw, self.cwd, self.scope, CHECKS, dirty={x}, saved=True)[0], "flag")
        self.assertEqual(classify(raw, self.cwd, self.scope, CHECKS, own={x})[0], "flag")

    def test_remembered_rules(self):
        rules = ["write:modules/offtrip/**", r"cmd:make (gen|lint)"]
        self.assertTrue(rule_matches(rules, {"path": "modules/offtrip/a/b.go", "command": "create"}, self.cwd))
        self.assertFalse(rule_matches(rules, {"path": "modules/other/b.go", "command": "create"}, self.cwd))
        self.assertTrue(rule_matches(rules, {"command": "make gen"}, self.cwd))
        self.assertFalse(rule_matches(rules, {"command": "make gen; rm x"}, self.cwd))

    def test_snapshot_keeps_untracked_and_leaves_index_alone(self):
        repo = self.cwd
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                        "commit", "-qm", "init"], cwd=repo, check=True)
        (repo / "pkg/x/x.go").write_text("package x\n// changed\n")
        (repo / "pkg/x/new.go").write_text("package x\n// new\n")
        out = repo / "q" / "snapshot.patch"
        out.parent.mkdir()
        self.assertTrue(snapshot(repo, out))
        patch = out.read_text()
        self.assertIn("// changed", patch)
        self.assertIn("// new", patch)
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True).stdout
        self.assertEqual(staged, "")  # the real index is untouched

    def test_next_event(self):
        q = self.cwd / "q"
        q.mkdir()
        (q / "req-1.json").write_text('{"n": 1}')
        (q / "resp-1.json").write_text('{"allow": true}')
        (q / "req-2.json").write_text('{"n": 2}')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            next_event(q, 2)
        self.assertEqual(out.getvalue().strip(), '{"n": 2}')
        (q / "resp-2.json").write_text('{"allow": true}')
        (q / "done.json").write_text('{"session": "s"}')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            next_event(q, 2)
        self.assertEqual(out.getvalue().strip(), "DONE session=s")

    def test_dirty_files(self):
        repo = self.cwd
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                        "commit", "-qm", "init"], cwd=repo, check=True)
        (repo / "pkg/x/x.go").write_text("package x\n// changed\n")
        (repo / "pkg/x/new.go").write_text("package x\n")
        self.assertEqual(dirty_files(repo), {str(repo / "pkg/x/x.go"), str(repo / "pkg/x/new.go")})


if __name__ == "__main__":
    unittest.main()
