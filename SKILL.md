---
name: opus-consultant
description: Invoke Claude Opus as an on-demand consultant for hard reasoning problems — code review, architecture decisions, "is this approach sound?" Package the question plus context and run consult.py; Opus investigates with scoped read-only tools under a spend cap and returns a recommendation. Use when a second opinion from a stronger reasoner is worth the API cost, not for routine tasks the primary agent can handle.
---

# Opus Consultant

When you hit a problem where a second opinion from a stronger reasoner is
worth real API money, consult Opus. You do the orchestration; Opus does the
deep thinking on one scoped question.

## Setup

```bash
cd /path/to/opus-consultant
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Auth: either export ANTHROPIC_API_KEY=sk-ant-... (env only — never write it
# to a file), or sign the Claude Code CLI in once with `claude auth login`
# and skip the key entirely — the SDK delegates auth to the CLI, so a Claude
# subscription works.
```

## When to consult

- Architecture or design decisions with real trade-offs.
- "Is this approach sound?" / "What am I missing?" reviews.
- Tricky debugging where you've gone in circles.
- Security-sensitive code review.

Do NOT consult for: routine implementation, tasks with no clear question,
anything where the context can't be packaged into a prompt + files.

## How to consult

1. Write the question as one sharp `--task` string.
2. Gather the minimal sufficient context: relevant files, error output, your
   current thinking. Put prose in a `--context` file; point `--workdir` at the
   repo so Opus can read around (read-only by default).
3. Run:
   ```bash
   python consult.py --task "<sharp question>" --context ./ctx.md \
     --workdir /path/to/repo --json
   ```
4. Read `.result` for the recommendation; check `.total_cost_usd` to stay
   aware of spend.

## Guardrails

- Default caps: **$3.00** and **8 turns** per consultation
  (`CONSULTANT_MAX_BUDGET_USD`, `CONSULTANT_MAX_TURNS`, or the flags).
- Tools are read-only (`read_file`, `list_dir`, `grep`) unless you pass
  `--allow-shell`. The shell is timeout-bounded and cwd-jailed. The model is
  allow-listed to exactly these tools, so the CLI's built-in tools (Bash,
  Write, …) are not reachable — the read-only guarantee holds by
  construction, not just by prompting.
- `--dry-run` shows exactly what would be sent before spending anything.
- The API key lives in the environment only. Never echo it, log it, or put
  it in a file. With `claude auth login` there is no key at all.
