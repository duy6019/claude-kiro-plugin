---
description: Ask Kiro to cross-review a git diff (read-only)
argument-hint: '<repo path> [--base <ref>]'
disable-model-invocation: true
allowed-tools: Read, Bash(cd:*), Bash(git:*), Bash(mktemp:*), Bash(kiro-cli:*), AskUserQuestion
---

Get a second opinion from Kiro on a diff.

Raw slash-command arguments:
`$ARGUMENTS`

Core constraint: review only. Do not edit code, commit, or apply anything.

Steps:
1. Take the repo path from the arguments. Use the ref after `--base` if given; otherwise the remote default branch from `git -C <repo> symbolic-ref --short refs/remotes/origin/HEAD`, falling back to `origin/main`.
2. Create the file with `mktemp -t kiro-review-XXXX.diff`, then run `git -C <repo> diff <base>...HEAD` with output redirected to it. Do not check out or fetch anything.
3. If the diff is empty, say so and stop.
4. From the repo directory, run `kiro-cli chat --no-interactive --trust-tools=read,glob,grep 'Review the diff in <file>. Read the surrounding code in this repo when needed. Report bugs, risks and missing tests. Cite file:line. Do not suggest edits you cannot justify from the code.'`. Do not wrap it in `timeout`; set the Bash tool timeout to 300000 ms.
5. Return Kiro's findings verbatim. Add one line: these are Kiro's unverified findings; check each one against the code before acting.
6. Delete the temp file with `rm -f <file>` (not in `allowed-tools`, so the user approves it).

Permission denied:
- Kiro exits 0 even when a tool is blocked, so check the output for `[denied]`.
- If present, show the `[tool]` lines before it. Review stays read-only: never add `write` or `shell`; report what Kiro could not do and continue.
- Never add `-a` or `--trust-all-tools`.
