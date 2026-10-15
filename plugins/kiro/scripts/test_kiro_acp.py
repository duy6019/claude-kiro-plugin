#!/usr/bin/env python3
"""Self-test for the permission tiers in kiro_acp.py: python3 test_kiro_acp.py"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kiro_acp import classify, dirty_files  # noqa: E402

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
        for c in ("go test ./pkg/x/... -timeout 300s && echo done", "git diff --output=x", "make generate",
                  "go test ./... -timeout 900s"):
            self.assertEqual(self.tier(command=c), "ask", c)

    def test_other_tools_ask(self):
        self.assertEqual(self.tier(url="https://example.com"), "ask")

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
