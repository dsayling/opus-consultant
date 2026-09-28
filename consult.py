#!/usr/bin/env python3
"""opus-consultant: invoke Claude Opus as an on-demand consultant.

A portable wrapper around the Claude Agent SDK. You (or your agent) provide
a task/question plus background context; Opus investigates with a small set
of scoped, read-only tools and returns a recommendation.

The API key is read ONLY from the ANTHROPIC_API_KEY environment variable.
It is never written to disk, never logged, and never echoed.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python consult.py --task "Is this caching approach sound?" \
        --context ./notes.md --workdir ./myrepo --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    create_sdk_mcp_server,
    query,
    tool,
)
from claude_agent_sdk.types import ResultMessage

DEFAULT_MODEL = os.environ.get("CONSULTANT_MODEL", "opus")
DEFAULT_MAX_BUDGET_USD = float(os.environ.get("CONSULTANT_MAX_BUDGET_USD", "3.00"))
DEFAULT_MAX_TURNS = int(os.environ.get("CONSULTANT_MAX_TURNS", "8"))

READ_CHAR_LIMIT = 100_000
GREP_RESULT_LIMIT = 50
SHELL_OUTPUT_LIMIT = 20_000
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".hg", ".svn"}


CONSULTANT_SYSTEM_PROMPT = """\
You are an expert consultant, not the primary agent. A primary agent has
handed you a specific question along with background context.

Rules:
- Answer the question asked. Stay scoped; do not go exploring beyond what
  the question needs.
- Use the provided tools to inspect files and context when it helps. You
  cannot edit anything (no write tools exist); read and reason.
- Be concise and concrete. Lead with the answer, then the reasoning.
- End with a clear recommendation or verdict.
- If the context is insufficient, say what is missing instead of guessing.
"""


def build_tools(workdir: Path, allow_shell: bool, shell_timeout: int):
    """Define the scoped tool surface Opus is allowed to use."""

    def safe_path(p: str) -> Path:
        target = (workdir / p).resolve()
        if target != workdir and workdir not in target.parents:
            raise ValueError(f"path escapes workdir: {p!r}")
        return target

    def ok(text: str) -> dict:
        return {"content": [{"type": "text", "text": text}]}

    def err(text: str) -> dict:
        return {"content": [{"type": "text", "text": text}], "is_error": True}

    @tool(
        "read_file",
        "Read a text file inside the workdir. Path is relative to the workdir.",
        {"path": str},
    )
    async def read_file(args):
        try:
            text = safe_path(args["path"]).read_text(errors="replace")
        except Exception as e:
            return err(f"Error: {e}")
        if len(text) > READ_CHAR_LIMIT:
            text = text[:READ_CHAR_LIMIT] + "\n…[truncated]"
        return ok(text)

    @tool(
        "list_dir",
        "List entries in a directory inside the workdir. Path is relative to the workdir; defaults to '.'.",
        {"path": str},
    )
    async def list_dir(args):
        try:
            target = safe_path(args.get("path", "."))
            entries = sorted(
                (("dir " if p.is_dir() else "file ") + p.name)
                for p in target.iterdir()
            )
        except Exception as e:
            return err(f"Error: {e}")
        return ok("\n".join(entries) if entries else "(empty)")

    @tool(
        "grep",
        "Search file contents inside the workdir with a regex. Skips hidden dirs, .git, .venv, node_modules.",
        {"pattern": str, "path": str},
    )
    async def grep(args):
        try:
            root = safe_path(args.get("path", "."))
            rx = re.compile(args["pattern"])
        except Exception as e:
            return err(f"Error: {e}")
        hits: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                fp = Path(dirpath) / fn
                try:
                    text = fp.read_text(errors="strict")
                except Exception:
                    continue  # binary or unreadable
                for i, line in enumerate(text.splitlines(), 1):
                    if rx.search(line):
                        rel = fp.relative_to(workdir)
                        hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                        if len(hits) >= GREP_RESULT_LIMIT:
                            hits.append("…[truncated]")
                            return ok("\n".join(hits))
        return ok("\n".join(hits) if hits else "(no matches)")

    tools = [read_file, list_dir, grep]

    if allow_shell:

        @tool(
            "run_shell",
            f"Run a shell command inside the workdir (timeout {shell_timeout}s). Prefer the read-only tools when they suffice.",
            {"command": str},
        )
        async def run_shell(args):
            try:
                proc = await asyncio.create_subprocess_shell(
                    args["command"],
                    cwd=str(workdir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=shell_timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return err(f"Error: command timed out after {shell_timeout}s")
            except Exception as e:
                return err(f"Error: {e}")
            text = out.decode(errors="replace")
            if len(text) > SHELL_OUTPUT_LIMIT:
                text = text[:SHELL_OUTPUT_LIMIT] + "\n…[truncated]"
            return ok(f"[exit {proc.returncode}]\n{text}")

        tools.append(run_shell)

    return tools


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Ask Claude Opus for a second opinion as an on-demand consultant."
    )
    p.add_argument("--task", required=True, help="The question or task for the consultant.")
    p.add_argument("--context", help="Path to a file with background context (appended to the prompt).")
    p.add_argument("--workdir", default=os.getcwd(), help="Directory the consultant's tools are scoped to.")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Model ID or alias (default: %(default)s).")
    p.add_argument("--max-budget-usd", type=float, default=DEFAULT_MAX_BUDGET_USD,
                   help="Hard spend cap for this consultation (default: %(default)s).")
    p.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS,
                   help="Max agentic turns (default: %(default)s).")
    p.add_argument("--allow-shell", action="store_true",
                   help="Enable the run_shell tool (off by default; tools are otherwise read-only).")
    p.add_argument("--shell-timeout", type=int, default=60, help="Seconds before run_shell is killed.")
    p.add_argument("--json", action="store_true", help="Emit a machine-readable JSON envelope on stdout.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the composed prompt and options without calling the API.")
    return p.parse_args(argv)


async def run_consultation(args) -> dict:
    workdir = Path(args.workdir).resolve()
    if not workdir.is_dir():
        raise SystemExit(f"workdir does not exist: {workdir}")

    prompt = args.task.strip()
    if args.context:
        ctx_path = Path(args.context)
        if not ctx_path.is_file():
            raise SystemExit(f"context file not found: {ctx_path}")
        prompt += "\n\n---\nBackground context:\n" + ctx_path.read_text(errors="replace")

    tools = build_tools(workdir, args.allow_shell, args.shell_timeout)
    server = create_sdk_mcp_server("consultant-tools", tools=tools)

    options = ClaudeAgentOptions(
        model=args.model,
        system_prompt=CONSULTANT_SYSTEM_PROMPT,
        mcp_servers={"consultant": server},
        max_turns=args.max_turns,
        max_budget_usd=args.max_budget_usd,
        permission_mode="bypassPermissions",  # safe: tool surface is read-only unless --allow-shell
        cwd=str(workdir),
    )

    if args.dry_run:
        return {
            "dry_run": True,
            "model": args.model,
            "max_turns": args.max_turns,
            "max_budget_usd": args.max_budget_usd,
            "allow_shell": args.allow_shell,
            "workdir": str(workdir),
            "tools": [t.name for t in tools],
            "prompt": prompt,
        }

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is not set. Export it; it is never written to disk.")

    result_text = ""
    summary: dict = {"is_error": True, "result": "no ResultMessage received"}
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, ResultMessage):
            result_text = msg.result or ""
            summary = {
                "is_error": bool(msg.is_error),
                "result": result_text,
                "model": args.model,
                "num_turns": msg.num_turns,
                "total_cost_usd": msg.total_cost_usd,
                "duration_ms": msg.duration_ms,
            }
    return summary


def main(argv=None):
    args = parse_args(argv)
    try:
        summary = asyncio.run(run_consultation(args))
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        code = e.code
        sys.exit(code if isinstance(code, int) else 1)
    if args.json or args.dry_run:
        print(json.dumps(summary, indent=2))
    else:
        print(summary.get("result", ""))
        print(
            f"\n[consultation: {summary.get('num_turns', '?')} turns, "
            f"${summary.get('total_cost_usd', 0) or 0:.4f}, "
            f"model={summary.get('model', '?')}]",
            file=sys.stderr,
        )
    sys.exit(1 if summary.get("is_error") else 0)


if __name__ == "__main__":
    main()
