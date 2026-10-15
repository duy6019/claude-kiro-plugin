#!/usr/bin/env python3
"""Self-test for kiro_agent.py and kiro_watch.py: python3 test_scripts.py"""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kiro_agent import commands  # noqa: E402
from kiro_watch import summarize  # noqa: E402


class Agent(unittest.TestCase):
    def allowed(self, cmd, pkgs):
        return any(re.fullmatch(p, cmd) for p in commands(pkgs))  # Kiro full-matches allowedCommands

    def test_package_scope(self):
        for ok in ("go test ./pkg/x/... -timeout 300s", "go test ./pkg/x/... -timeout 300s -v -run TestA",
                   "go vet ./pkg/x/...", "gofmt -l pkg/x"):
            self.assertTrue(self.allowed(ok, ["./pkg/x/..."]), ok)
        for bad in ("go test ./... -timeout 300s", "go test ./pkg/x/... -timeout 300s -race",
                    "go test ./pkgYx/... -timeout 300s", "go test ./pkg/xy/... -timeout 300s", "gofmt -w pkg/x"):
            self.assertFalse(self.allowed(bad, ["./pkg/x"]), bad)

    def test_rejects_unsafe_package_paths(self):
        for p in ("pkg/x", "./pkg/x; rm -rf /", "./../other", "./pkg/$(id)"):
            with self.assertRaises(SystemExit, msg=p):
                commands([p])


class Watch(unittest.TestCase):
    def test_summary(self):
        ev = [{"type": "metadata", "data": {"sessionId": "s1", "contextUsagePercentage": 2.5}},
              {"type": "sessionUpdate", "data": {"update": {"sessionUpdate": "tool_call_update", "status": "completed",
                                                            "kind": "edit", "rawInput": {"path": "/r/a.go"}}}},
              {"type": "sessionUpdate", "data": {"update": {"sessionUpdate": "tool_call_update", "status": "failed",
                                                            "kind": "execute", "rawInput": {"command": "ls"},
                                                            "_meta": {"kiro": {"toolCallFailureReason": "permission_denied"}}}}},
              {"type": "runFinished", "data": {"status": "success", "finalText": "done"}}]
        s = summarize(json.dumps(e) for e in ev)
        self.assertEqual((s["session"], s["status"], s["final"]), ("s1", "success", "done"))
        self.assertEqual([c["target"] for c in s["calls"]], ["/r/a.go", "ls"])
        self.assertEqual(s["calls"][1]["reason"], "permission_denied")


if __name__ == "__main__":
    unittest.main()
