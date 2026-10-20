---
name: kiro-spec
description: Have Kiro write a Kiro spec (requirements or bugfix doc, design.md, tasks.md, .config.kiro) under <dir>/.kiro/specs/<name>/, with Claude as the gate that checks it. Use when the user asks for a Kiro spec, "spec và tasks", or a spec for Kiro to implement.
---

# Kiro spec

Kiro writes the spec; Claude gates it. Keep the gate light: the structure check is automatic, and every task is
checked again when `/kiro:run` implements it. Stay quiet while Kiro works.

Paths: `R=<this skill's base directory>/../../scripts/kiro_acp.py`, `C=<this skill's base directory>/check_spec.py`,
`F=<this skill's base directory>/FORMAT.md` (the format rules Kiro follows).

1. **Inputs.** The topic (a Jira key, MR or description) and the working directory `<dir>`. Choosing `<dir>` follows
   your normal workflow and the workspace `CLAUDE.md`. Ask once, together: feature or bugfix; requirements-first or
   design-first (it cannot change later in Kiro); the prose language. Pick a kebab-case `<name>`.
2. **Prompt** in `<work>/spec/prompt.txt` (`<work>` = `reviews/_work/kiro-<name>/` in this workspace, else a temp dir):
   "Create a Kiro <feature | bugfix> spec named <name> in <dir>/.kiro/specs/<name>/ (<workflow>, prose in <language>)
   for: <topic, with the Jira/MR text you gathered>. Read <F> first and follow it exactly. Read the code the spec
   touches. Write .config.kiro, <requirements.md | bugfix.md>, design.md and tasks.md with your write tool. Do not
   change any other file. List open questions at the end of the requirements file instead of guessing."
3. **Run** in the background: `python3 $R --cwd <dir> --queue <work>/spec --prompt-file <work>/spec/prompt.txt
   --scope .kiro/specs/<name>`, with a `Monitor` on `python3 $R --watch <work>/spec`. Answer any request it hands you as
   `/kiro:run` step 10 describes; writes outside the spec directory should not be needed, so reject them with that reason.
4. **Gate** when it finishes:
   - `python3 $C <dir>/.kiro/specs/<name>`: every error goes back to Kiro (rerun with `--load <session>` and the error
     list). At most two rounds.
   - `git -C <dir> status --short`: only the spec directory changed.
   - Skim the requirements: they cover the topic and nothing else. Do not review wording or design detail.
5. **Hand over** in a few lines: the spec path, the number of requirements and tasks, Kiro's open questions, and
   check_spec warnings if any. The user approves or asks for changes; send changes to Kiro with `--load`.
6. Do not implement the spec unless the user asks; `/kiro:run <dir> <name>` does that.

When Claude itself edits a spec file, use the Write or Edit tool: the plugin's PostToolUse hook checks the structure.
