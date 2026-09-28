# opus-consultant

Give any agent a second brain: invoke Claude Opus as an **on-demand consultant**
via the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agent-sdk).

The pattern: your primary agent (or you) does the orchestration, file work, and
tool loops. When it hits a genuinely hard reasoning problem — a tricky code
review, an architecture decision, a "is this approach sound?" — it packages the
relevant context and asks Opus for a second opinion. Opus gets a small, scoped,
read-only tool surface (plus an opt-in shell), a hard spend cap, and a turn
limit. It answers, it doesn't roam.

This is deliberately **not** "Opus as a subagent." A subagent inherits your
harness's transcript, tools, and memory. A consultant is a separate brain you
invoke with a scoped question — cheaper to reason about, easier to bound, and
portable across harnesses.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # never committed, never logged
```

## Usage

```bash
# Ask a question with background context, scoped to a repo
python consult.py \
  --task "Is this caching approach sound? What would you change?" \
  --context ./notes.md \
  --workdir ./myrepo

# Machine-readable output for agent harnesses
python consult.py --task "..." --json | jq .result

# Allow Opus to run (read-only-ish) shell commands in the workdir
python consult.py --task "..." --allow-shell

# Tune the guardrails
python consult.py --task "..." --max-budget-usd 1.00 --max-turns 5

# See exactly what would be sent, without spending anything
python consult.py --task "..." --dry-run
```

Environment knobs (override the flags' defaults):

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** Read from env only. |
| `CONSULTANT_MODEL` | `opus` | Model ID or alias. Use a full ID (e.g. `claude-opus-4-1-20250805`) if the alias doesn't resolve. |
| `CONSULTANT_MAX_BUDGET_USD` | `3.00` | Hard spend cap per consultation. |
| `CONSULTANT_MAX_TURNS` | `8` | Max agentic turns per consultation. |

## How it works

- `consult.py` is a single-file CLI. No packaging, no framework beyond the SDK.
- Opus gets three read-only tools scoped to `--workdir` with path-traversal
  guards: `read_file`, `list_dir`, `grep`. `--allow-shell` adds `run_shell`
  (timeout-bounded, cwd-jailed).
- `max_budget_usd` is enforced by the SDK itself — the consultation stops when
  the cap is hit.
- The consultant system prompt frames Opus as an advisor: answer the question,
  stay scoped, lead with the answer, end with a recommendation.
- `--json` emits `{"result", "total_cost_usd", "num_turns", "model", "is_error"}`
  for easy parsing by a calling agent.

## As an agent skill

`SKILL.md` follows the [Agent Skills](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills)
open format, so it loads in Claude Code and other skill-aware harnesses, not
just the one it was born in. See `examples/` for harness-specific wiring.

## License

MIT — see [LICENSE](LICENSE).
