---
description: Implement a Kiro spec with Kiro, one top-level task at a time, each in a task-scoped agent, checked by Claude
argument-hint: '<repo path> <spec name> [task numbers]'
disable-model-invocation: true
allowed-tools: Read, Bash(cd:*), Bash(mkdir -p:*), Bash(cp -r:*), Bash(git:*), Bash(kiro-cli:*), Bash(python3:*), Bash(gofmt:*), Bash(go vet:*), Bash(go test:*), AskUserQuestion
---

Drive Kiro through a spec. Kiro writes the code; Claude sets each task's permissions and checks the result.

Raw slash-command arguments:
`$ARGUMENTS`

Scripts: `A="${CLAUDE_PLUGIN_ROOT}/scripts/kiro_agent.py"`, `W="${CLAUDE_PLUGIN_ROOT}/scripts/kiro_watch.py"`, `C="${CLAUDE_PLUGIN_ROOT}/skills/kiro-spec/check_spec.py"`.

## Setup (once)

1. Spec dir is `<repo>/.kiro/specs/<spec name>`. Run `python3 $C <spec dir>`; stop on errors.
2. Follow the workspace `CLAUDE.md`: show `git -C <repo> branch --show-current`, `status --short`, `worktree list`, and ask with `AskUserQuestion` where Kiro works:
   - New worktree (recommended): `git -C <repo> worktree add --detach <session folder>/.review-wt/<repo>-<branch> <branch>`; if the session folder is a repo, add `.review-wt/` to its `.git/info/exclude` first.
   - Current checkout: list its uncommitted changes in the question.
   Call the chosen directory `<dir>`; all paths below are absolute under it.
   A new worktree holds only committed files, so copy the spec there first: `mkdir -p <dir>/.kiro/specs && cp -r <repo>/.kiro/specs/<spec name> <dir>/.kiro/specs/`. The copy shows as untracked in the worktree; ignore it in the step 10 file check. From then on `<spec dir>` means the copy in `<dir>`: check it, give it to Kiro, and mark tasks in it. Tell the user the main copy's `tasks.md` will not show progress.
3. In the same question, ask whether Kiro should also do the optional `[ ]*` test sub-tasks (Kiro skips them by default).
4. Logs go to `reviews/_work/` in this workspace if it exists, otherwise to a `mktemp -d` directory. Never into `<dir>`.
5. Tasks to run: the given numbers, or every top-level task not marked `[x]`, in order.

## Per top-level task N

6. **Scope.** From task N, its sub-tasks and `design.md`, list the files to create or change and their Go packages. Write globs: those files (or their package directories when new files are expected) plus `<spec dir>/tasks.md`. For a task that only adds or changes tests, use `<pkg dir>/**/*_test.go` so Kiro itself blocks production edits. Show the scope in a short list. If task N names no files, propose a scope and ask before running.
7. **Agent.** `python3 $A create claude-kiro-<spec>-t<N> --write <globs> --pkg <./pkg/path>...`. It allows only read/glob/grep, writes inside the globs, and exact `go test <pkg>/... -timeout 300s` (optional `-v`, `-run X`, `-count=1`), `go vet <pkg>/...`, `gofmt -l <pkg>`. Kiro rejects chained commands even then.
8. **Run** from `<dir>` with the Bash tool's `run_in_background`:
   `kiro-cli chat --output-format stream-json --agent claude-kiro-<spec>-t<N> [--resume-id <session>] '<prompt>' > <log>/kiro-<spec>-t<N>.jsonl 2>&1`
   - Add `--resume-id` from task 2 on, so Kiro keeps what it already read.
   - Prompt: "Implement task N of the Kiro spec in <spec dir>. Read requirements.md (or bugfix.md), design.md and tasks.md first. Do only task N and its sub-tasks, in order, one tool call at a time, never in parallel. <Do / skip> sub-tasks marked [ ]*. You may write only: <files>. You may run only: <commands>. If a write or command is denied, do not retry or work around it; finish what you can and report what you needed and why. Mark each finished sub-task [x] in tasks.md. End with the files you changed and the test results."
   - Single-quote the prompt (`'` becomes `'\''`). Never pass `--trust-tools`, `-a` or `--trust-all-tools`.
9. **Watch.** When the run finishes, read only `python3 $W <log file>`, not the raw log.
   - Keep the session id for the next task.
   - A denied call that the task really needs: ask the user before recreating the agent with the wider scope, then resume with "continue task N".
   - A denied call outside the task: Kiro drifted. Resume with a short note to stay in scope, or report it.
   - Context above 70%: tell the user; start the next task without `--resume-id`.
10. **Check** (Claude, in `<dir>`):
    - `git -C <dir> status --short` and `diff --stat`: only files in scope changed. Report anything else, such as regenerated swagger under `api/docs/proto/**`.
    - `gofmt -l`, `go vet` and `go test -timeout 300s` on the touched packages only.
    - Read the diff: it does what task N says and meets the requirement clauses it cites; it does not touch production code in a tests-only task or change unrelated behaviour.
    - If something is wrong, resume the same session with a numbered list of fixes. At most two fix rounds, then stop and report.
11. Pass: `python3 $A delete claude-kiro-<spec>-t<N>`, then the next task.

## Checkpoint tasks

12. Claude runs them itself: `go test ./... -timeout 300s` in `<dir>`. Report failures to the user before continuing, and mark the checkpoint `[x]` only when it passes.

## End

13. Run `go test ./... -race -timeout 300s` once and `python3 $C <spec dir>`.
14. Report per task: files changed, test results, denied calls, findings, and what is not verified (for example tests that need Docker).
15. Delete every `claude-kiro-<spec>-*` agent you created. Do not commit, push or revert. Leave a worktree with changes in place and tell the user where it is.
