---
description: Ask kiro-cli a question without letting it change anything
argument-hint: '[--read] <question>'
disable-model-invocation: true
allowed-tools: Bash(kiro-cli:*), AskUserQuestion
---

Ask Kiro through its CLI and return the answer.

Raw slash-command arguments:
`$ARGUMENTS`

Rules:
- If the arguments start with `--read`, strip that flag and use `--trust-tools=read,glob,grep`. Otherwise use `--trust-tools=` (no tools).
- Run `kiro-cli chat --no-interactive --trust-tools=<tools> '<question>'` from the current directory.
- Wrap the question in single quotes; write each `'` inside it as `'\''`. Do not wrap the command in `timeout` or anything else, so it matches `allowed-tools`.
- Set the Bash tool timeout to 300000 ms.
- Return Kiro's output verbatim, then one line saying it is Kiro's answer and was not verified.
- If `kiro-cli` is missing or exits non-zero, show the error and stop.

Permission denied:
- Kiro exits 0 even when a tool is blocked, so check the output for `[denied]`.
- If present, show the `[tool]` lines before it (what Kiro tried) and ask with `AskUserQuestion` whether to re-run with that tool added.
- Map the `[tool]` line to a tool name yourself. This command may only add read-only tools: `read`, `glob`, `grep`, `web_fetch`, `web_search`. `web_*` sends data outside, so name it in the question.
- If Kiro needs `write` or `shell`, say so and point to `/kiro:run`. Never add `-a` or `--trust-all-tools`.
