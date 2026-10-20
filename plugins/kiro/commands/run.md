---
description: Implement a Kiro spec with Kiro over ACP in one run; Claude answers the few permission requests Kiro raises and gates the result once at the end. Use only when the user asks Kiro to implement a spec or to run /kiro:run.
argument-hint: '<working dir> <spec name> [task numbers]'
allowed-tools: Read, Write, Bash(mkdir -p:*), Bash(cp -r:*), Bash(git:*), Bash(python3:*), Monitor, AskUserQuestion
---

Kiro implements the whole spec, running its own tests and checkpoints; Claude is a light gate. Kiro's global steering (ponytail) shapes how it works, so keep prompts short.

**Stay quiet while it runs.** No chat text for starting the run, arming the Monitor, waiting, or a request you allowed (after writing an allowing `resp-<n>.json`, end the turn with no text). Speak only to ask the user, to report a rejection or a failure, and at the end.

Raw slash-command arguments:
`$ARGUMENTS`

Scripts: `R="${CLAUDE_PLUGIN_ROOT}/scripts/kiro_acp.py"`, `C="${CLAUDE_PLUGIN_ROOT}/skills/kiro-spec/check_spec.py"`.

## Setup

1. **Working directory.** `<dir>` is where Kiro works. Choosing or creating it (checkout or worktree) follows your normal workflow and the workspace `CLAUDE.md`. If `<dir>` lacks the spec (for example it is uncommitted in another checkout), copy it in: `mkdir -p <dir>/.kiro/specs && cp -r <source>/.kiro/specs/<spec name> <dir>/.kiro/specs/`, and ignore that copy in the file checks.
2. `<spec dir>` is `<dir>/.kiro/specs/<spec name>`. Run `python3 $C <spec dir>`; stop on errors.
3. Ask the user once whether Kiro should also do the optional `[ ]*` sub-tasks (unit tests are never optional).
4. **Check commands.** Find how this repo builds, lints and tests (Makefile, CI config, package.json, pyproject, go.mod, README). Turn them into full-match (Python) regexes for `--allow-cmd` that accept flags in any order. For Go: `'go test( \S+)* -timeout (300|[12][0-9]{2}|[1-9][0-9]?)s( \S+)*'` and `'go vet( \S+)+'`; for npm: `'npm (run )?test( \S+)*'`. Follow the workspace rules (in the fraud repos every `go test` carries `-timeout` ≤ 300s).
5. Work files go to `reviews/_work/kiro-<spec>/` in this workspace if `reviews/_work` exists, otherwise to a `mktemp -d` directory. Never into `<dir>`.

## Run

6. **Prompt** in `<work>/run/prompt.txt`: "Implement the Kiro spec in <spec dir>: every top-level task not marked [x] (or: tasks <numbers>), in order, <including / skipping> the [ ]* sub-tasks. Run the tests yourself, also for the checkpoint tasks. Mark finished tasks [x] in tasks.md. Change files with your write tool, not shell commands."
7. Start it with the Bash tool's `run_in_background`:
   `python3 $R --cwd <dir> --queue <work>/run --prompt-file <work>/run/prompt.txt --scope <spec dir> --allow-cmd <regexes> > <work>/run/runner.out 2>&1`
   and a `Monitor` with exactly `python3 $R --watch <work>/run` (timeout 30 minutes; re-arm it if it expires before `DONE` or `ERROR`).
8. **Answer what the runner hands you.** By default Kiro runs in a bubblewrap sandbox (read-only filesystem except `<dir>`, no credentials, no user sockets), and the runner allows almost everything itself. It still rejects history-changing or remote git, forced deletes, sudo and network tools, and it asks you about overwriting uncommitted work, database clients and, without the sandbox, unknown commands. Answer with `<work>/run/resp-<n>.json`: `{"allow": true|false, "reason": "<one line>"}`:
   - Allow what the spec needs, even when it breaks existing code or tests that the same spec then fixes; when unsure, allow what can be recovered.
   - Reject only work lost for good with no reason in the spec, citing what you based it on.
   - Ask the user when the request touches the user's own uncommitted changes or when the workspace `CLAUDE.md` would make you ask before doing it yourself. Never grant Kiro what you could not do yourself.
   - If the runner printed `sandbox: off`, say so in the final report.

## Gate (once, at the end)

9. When the run ends:
   - Run the repo's full test and lint commands in `<dir>` (with the race detector if the repo uses one).
   - `git -C <dir> diff`: grep removed lines for deleted test functions or cases (`func Test`, `def test_`, `it(`, `test(`).
   - `python3 $C <spec dir>` and check that every task Kiro was asked to do is `[x]` (skipped `[ ]*` sub-tasks stay open).
   - Any failure: run again with `--load <session from done.json>` and a numbered list of the failures. At most two rounds, then stop and report.
   - Do not read the diff line by line; the spec's own tests and checkpoints are the detailed check.
10. **Report** in a few lines: result; tasks done; checks; rejected or asked permissions with their reason; Kiro's stated risks; what is not verified (for example tests that need Docker); the next step.
11. Do not commit, push or revert.
