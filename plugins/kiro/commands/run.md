---
description: Let Kiro edit files in a checkout you choose (read, write only), then verify the result
argument-hint: '<repo path> <branch> <task>'
disable-model-invocation: true
allowed-tools: Read, Bash(cd:*), Bash(git:*), Bash(kiro-cli:*), Bash(gofmt:*), Bash(go vet:*), Bash(go test:*), AskUserQuestion
---

Delegate a code change to Kiro, then check what it did.

Raw slash-command arguments:
`$ARGUMENTS`

Rules:
1. Follow the workspace `CLAUDE.md`. Run `git -C <repo> branch --show-current`, `status --short` and `worktree list`, then ask with `AskUserQuestion` where Kiro should write:
   - New worktree (recommended): `git -C <repo> worktree add --detach <session folder>/.review-wt/<repo>-<branch> <branch>` (`/` in the branch becomes `-`). `--detach` is needed because the branch is usually checked out in the main copy already. If the session folder is itself a repo, first add `.review-wt/` to that repo's `.git/info/exclude`.
   - Current checkout: only if it is on `<branch>`. List its uncommitted changes in the question so the user sees what Kiro will write next to.
2. From the chosen directory, run `kiro-cli chat --no-interactive --trust-tools=read,write,glob,grep '<task>'`.
   - Put absolute paths in the task text. Kiro has resolved a relative path against the workspace root instead of its cwd.
   - Tell Kiro which files it may create or change, and that production code is off limits unless the task says otherwise.
   - Single-quote the task (`'` becomes `'\''`). Do not wrap it in `timeout`; set the Bash tool timeout to 300000 ms.
   - Never add `shell`, `-a` or `--trust-all-tools`.
3. If the output contains `[denied]`, look at the `[tool]` line before it:
   - `shell` (Kiro tried to run tests or commands): do not offer it. Step 5 does the verification. Continue.
   - Any other tool: show the line and ask before re-running with that tool added.
4. Show `git -C <dir> status --short` and `git -C <dir> diff --stat`. If a worktree was used, also run `git -C <repo> status --short` to catch files Kiro wrote in the main copy.
5. Kiro has no shell, so verify yourself. For Go: `gofmt -l`, `go vet` and `go test -timeout 300s` on the touched packages. Report the results; failing checks are findings, not something to hide.
6. Do not commit, push or revert. Leave the change for the user, and offer to export it as a patch under `reviews/`.
7. When done, remove a worktree this command created only if `git status --short` in it is clean; never `--force`.
