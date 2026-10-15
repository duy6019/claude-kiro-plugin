---
description: Implement a Kiro spec with Kiro over ACP, one top-level task at a time; Claude answers Kiro's permission requests, checks lightly after each task and reviews in depth at checkpoints. Use only when the user asks Kiro to implement a spec or to run /kiro:run.
argument-hint: '<working dir> <spec name> [task numbers]'
allowed-tools: Read, Write, Bash(mkdir -p:*), Bash(cp -r:*), Bash(git:*), Bash(python3:*), Monitor, AskUserQuestion
---

Drive Kiro through a spec. Kiro decides how to do each task and asks before every write and shell command; Claude answers those requests and judges the result. Kiro's global steering (ponytail) shapes how it works, so keep prompts short.

**Stay quiet while it runs.** No chat text for starting a run, arming the Monitor, waiting, or a request you allowed. Speak only to ask the user, to report a rejection or a failed task, after each task (one line, step 11) and at the end (step 14). Decision reasons live in `done.json`, not in chat. After writing a `resp-<n>.json` that allows, end the turn with no text.

Raw slash-command arguments:
`$ARGUMENTS`

Scripts: `R="${CLAUDE_PLUGIN_ROOT}/scripts/kiro_acp.py"`, `C="${CLAUDE_PLUGIN_ROOT}/skills/kiro-spec/check_spec.py"`.

## Setup (once)

1. **Working directory.** `<dir>` is where Kiro works. Choosing or creating it (checkout or worktree) follows your normal workflow and the workspace `CLAUDE.md`; this command does not do it. If `<dir>` lacks the spec (for example it is uncommitted in another checkout), copy it in: `mkdir -p <dir>/.kiro/specs && cp -r <source>/.kiro/specs/<spec name> <dir>/.kiro/specs/`, and ignore that copy in the file checks.
2. `<spec dir>` is `<dir>/.kiro/specs/<spec name>`. Run `python3 $C <spec dir>`; stop on errors.
3. Ask the user once whether Kiro should also do the optional `[ ]*` test sub-tasks.
4. **Check commands.** Find how this repo builds, lints and tests (Makefile, CI config, package.json, pyproject, go.mod, README). Turn them into full-match (Python) regexes for `--allow-cmd` that accept flags in any order; commands are matched after quotes are removed and pipes split off. For Go: `'go test( \S+)* -timeout (300|[12][0-9]{2}|[1-9][0-9]?)s( \S+)*'` and `'go vet( \S+)+'`; for npm: `'npm (run )?test( \S+)*'`. Follow the workspace rules (in the fraud repos every `go test` carries `-timeout` ≤ 300s).
5. Work files go to `reviews/_work/kiro-<spec>/` in this workspace if `reviews/_work` exists, otherwise to a `mktemp -d` directory. Never into `<dir>`.
6. Tasks to run: the given numbers, or every top-level task not marked `[x]`, in order.

## Per top-level task N

7. **Scope.** From task N and `design.md`, list the files or directories you expect Kiro to write, plus `<spec dir>/tasks.md`. It is a prediction, not a fence: writes elsewhere inside `<dir>` are allowed and flagged for review.
8. **Prompt.** Write `<work>/t<N>/prompt.txt`: "Implement task N of the Kiro spec in <spec dir>, <including / skipping> the [ ]* sub-tasks. Mark finished sub-tasks [x] in tasks.md. Change files with your write tool, not shell commands." Add a line only for something a previous run showed: a specific problem, or the requests you rejected and why, inviting Kiro to explain if it still needs them.
9. **Run** with the Bash tool's `run_in_background`:
   `python3 $R --cwd <dir> --queue <work>/t<N> --prompt-file <work>/t<N>/prompt.txt --scope <paths> --allow-cmd <regexes> [--load <session>] > <work>/t<N>/runner.out 2>&1`
   From task 2 on, pass `--load` with the session id from the previous `done.json`, so Kiro keeps what it already read.
10. **Answer what the runner hands you.** It allows writes inside `<dir>` (flagging those outside the predicted scope or overwriting a committed file), read-only git and the check commands, also when piped or chained with `echo`, `tail`, `head`, `grep` or `wc`; it rejects writes outside `<dir>`, history-changing or remote git, recursive or forced deletes, sudo and network tools. It asks you about overwriting uncommitted work and about any other command.
    - Start a `Monitor` with exactly `python3 $R --watch <work>/t<N>` (timeout 30 minutes). It prints `ASK <n>: reason | target | read_before | purpose` for each request waiting for you and ends with `DONE` or `ERROR`. Re-arm it if it expires first. `ERROR`, or a runner that exits without `done.json`, is a failed task. Unanswered requests are rejected after `--ask-timeout` (20 minutes by default).
    - Answer with `<work>/t<N>/resp-<n>.json`: `{"allow": true|false, "reason": "<one line>"}`. Decide like this:
      1. Judge against the task and the spec (requirement clauses, `design.md`) and Kiro's stated purpose, not your own preference. If the task needs the change, allow it, even when it breaks existing code or tests; fixing those belongs to the same task.
      2. When unsure, allow if the result can be recovered (the old content is committed, or the new content keeps the uncommitted part), and verify in the light check.
      3. Reject only when uncommitted work would be lost for good and the task gives no reason for it. The reason must cite what you based it on (task number, requirement clause, or the lost content). Pass it to Kiro in the next run so it can explain; allow it then if the explanation holds.
      4. Ask the user when the request touches the user's own uncommitted changes, or when the spec is unclear whether the business need calls for it. Also ask whenever the workspace `CLAUDE.md` would make you ask before doing it yourself (hard to reverse, outward-facing). Kiro runs commands as the user and bypasses Claude Code's permission prompts, so never grant Kiro what you could not do yourself.
    - Allowed check commands run test code that Kiro wrote; that is another reason to work in a worktree.
11. **Light check** when the run ends (the runner prints calls, decisions and Kiro's final text):
    - Read Kiro's closing lines (what it skipped, the risks).
    - Look at every `flag` decision: is the extra file or the overwrite justified by the task?
    - `git -C <dir> diff`: grep removed lines for deleted test functions or cases (`func Test`, `def test_`, `it(`, `test(`).
    - Run the repo's check commands on the changed parts.
    - Anything wrong: run again with `--load` and a prompt naming the specific problem. At most two fix rounds, then stop and report.
    - Then write one line: `Task N ✅|❌ <what changed, a few words> · checks <pass/fail> · <n> allowed, <n> flagged, <n> rejected · <Kiro's risk, if any>`.

## Checkpoint tasks: review the cluster

12. At each Checkpoint task (and after the last task when the spec has none):
    - Run the repo's full test command in `<dir>`.
    - Read the diff of the tasks done since the last checkpoint against the requirement clauses they cite and `design.md`: correct behaviour, nothing outside the tasks' intent, tests that assert something real.
    - Problems: send Kiro a numbered list (`--load`), then re-check. Clean: mark the checkpoint `[x]` in `<spec dir>/tasks.md`.

## End

13. Run the repo's full checks once more (with the race detector or equivalent if the repo uses one) and `python3 $C <spec dir>`.
14. Short report: the overall result in one line; one or two lines per task (what changed, fix rounds); only the flagged, asked or rejected permissions with their reason; checkpoint findings; what is not verified (for example tests that need Docker); the next step. Leave out allowed permissions and anything already said in the per-task lines.
15. Do not commit, push or revert.
