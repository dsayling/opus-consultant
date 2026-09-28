# Wiring opus-consultant into a Muse agent

This is an example; the core (`consult.py` + `SKILL.md`) is harness-agnostic.

## The pattern

1. The user's Anthropic API key lives in the agent's Secure Vault — never in
   chat, never in a file, never in the repo.
2. When the agent decides a consultation is warranted (see `SKILL.md` for the
   "when"), it writes the background context to a temp file and invokes:

   ```bash
   ANTHROPIC_API_KEY="$KEY_FROM_VAULT" \
     /path/to/opus-consultant/.venv/bin/python /path/to/opus-consultant/consult.py \
       --task "<sharp question>" \
       --context /tmp/consult-ctx.md \
       --workdir /path/to/repo \
       --json
   ```

3. The agent parses the JSON envelope: `.result` is the recommendation,
   `.total_cost_usd` / `.num_turns` go in the summary back to the user.

## Conventions

- The agent decides when to consult; the user doesn't need to ask. Good
  triggers: "I've gone in circles on this bug," architecture trade-offs,
  security-sensitive review.
- Default to the built-in caps ($3.00 / 8 turns). Raise them only for
  genuinely large questions, and say so when reporting back.
- Keep `--allow-shell` off unless Opus needs to run something (tests, a
  repro). The read-only tools cover most consultations.
- Report the cost alongside the recommendation — one line, e.g.
  "(Opus consult: 6 turns, $1.84)". Keeps the spend visible.
