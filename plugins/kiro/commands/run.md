---
description: Implement a Kiro spec with Kiro over ACP in one run, driven by a small Sonnet agent that answers Kiro's rare permission requests and gates the result once at the end. Use only when the user asks Kiro to implement a spec or to run /kiro:run.
argument-hint: '<working dir> <spec name> [task numbers]'
allowed-tools: Read, Write, Bash(mkdir -p:*), Bash(cp -r:*), Bash(git:*), Bash(python3:*), Agent, Monitor, AskUserQuestion
---

Kiro implements the whole spec, running its own tests and checkpoints. A `kiro:kiro-driver` agent (Sonnet, short context) answers the permission requests and runs the final gate, so this conversation is not woken for each request. Keep prompts short; Kiro's global steering (ponytail) shapes how it works.

Raw slash-command arguments:
`$ARGUMENTS`

Scripts: `R="${CLAUDE_PLUGIN_ROOT}/scripts/kiro_acp.py"`, `C="${CLAUDE_PLUGIN_ROOT}/skills/kiro-spec/check_spec.py"`.

## Setup (this conversation)

1. **Working directory.** `<dir>` is where Kiro works. Choosing or creating it (checkout or worktree) follows your normal workflow and the workspace `CLAUDE.md`. If `<dir>` lacks the spec (for example it is uncommitted in another checkout), copy it in: `mkdir -p <dir>/.kiro/specs && cp -r <source>/.kiro/specs/<spec name> <dir>/.kiro/specs/`.
2. `<spec dir>` is `<dir>/.kiro/specs/<spec name>`. Run `python3 $C <spec dir>`; stop on errors.
3. Ask the user once whether Kiro should also do the optional `[ ]*` sub-tasks (unit tests are never optional).
4. **Check commands.** Find how this repo builds, lints and tests (Makefile, CI config, package.json, pyproject, go.mod, README). Write full-match (Python) regexes for `--allow-cmd` that accept flags in any order. For Go: `'go test( \S+)* -timeout (300|[12][0-9]{2}|[1-9][0-9]?)s( \S+)*'` and `'go vet( \S+)+'`; for npm: `'npm (run )?test( \S+)*'`. Note the full test and lint commands for the gate (in the fraud repos every `go test` carries `-timeout` ≤ 300s).
5. `<queue>` is `reviews/_work/kiro-<spec>/run/` in this workspace if `reviews/_work` exists, otherwise a `mktemp -d` directory; never inside `<dir>`. Write `<queue>/prompt.txt`: "Implement the Kiro spec in <spec dir>: every top-level task not marked [x] (or: tasks <numbers>), in order, <including / skipping> the [ ]* sub-tasks. Run the tests yourself, also for the checkpoint tasks. Mark finished tasks [x] in tasks.md. Change files with your write tool, not shell commands."

## Run

6. Start the `kiro:kiro-driver` agent with the Agent tool and pass it: `R`, `C`, `<dir>`, `<spec dir>`, `<queue>`, the prompt file, `--scope <spec dir>` plus the paths named in `design.md`, the `--allow-cmd` regexes, and the full test and lint commands. Say nothing while it runs.
7. When it returns, relay its report in a few lines. For `needs user` items, ask the user; if they allow them, start the driver again with `--load <session>` and a prompt that names what was allowed.

If the `kiro:kiro-driver` agent type is not available, drive it yourself: run the runner with `run_in_background`, a `Monitor` on `python3 $R --watch <queue>`, answer requests as the agent file describes, then run its gate and report.

Kiro runs in a bubblewrap sandbox by default (read-only filesystem except `<dir>`, no credentials, no user sockets). Uncommitted changes in `<dir>` are saved to `<queue>/snapshot.patch` before Kiro starts. Do not commit, push or revert.
