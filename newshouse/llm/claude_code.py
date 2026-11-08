"""Backend that shells out to the Claude Code CLI in headless mode."""
from __future__ import annotations

import copy
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from newshouse.llm.backend import LLMError, empty_usage

log = logging.getLogger("newshouse.llm")


class ClaudeCodeBackend:
    def __init__(self, bin: str, cwd: Path, timeout_s: int = 600):
        self.bin = bin
        self.cwd = Path(cwd)
        self.timeout_s = timeout_s
        self.usage: dict[str, dict] = {}

    def snapshot(self) -> dict[str, dict]:
        return copy.deepcopy(self.usage)

    def reset(self) -> None:
        self.usage = {}

    def _account(self, env: dict, requested: str) -> None:
        u = env.get("usage") if isinstance(env.get("usage"), dict) else {}
        mu = env.get("modelUsage") if isinstance(env.get("modelUsage"), dict) else {}
        # modelUsage is keyed by model id; take the costliest entry as the call's model.
        model_id = max(mu, key=lambda k: (mu[k] or {}).get("costUSD", 0) or 0) if mu else requested

        def n(v) -> int:
            return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0

        row = {"calls": 1, "input": n(u.get("input_tokens")),
               "cache_read": n(u.get("cache_read_input_tokens")),
               "cache_create": n(u.get("cache_creation_input_tokens")),
               "output": n(u.get("output_tokens")),
               "cost": float(env.get("total_cost_usd") or 0),
               "turns": n(env.get("num_turns")), "api_ms": n(env.get("duration_api_ms"))}
        acc = self.usage.setdefault(model_id, empty_usage())
        for k, v in row.items():
            acc[k] += v
        log.info("llm call model=%s turns=%d in=%d cache_read=%d cache_create=%d out=%d "
                 "cost=%.6f api_ms=%d", model_id, row["turns"], row["input"], row["cache_read"],
                 row["cache_create"], row["output"], row["cost"], row["api_ms"])

    def complete_json(self, *, system: str, user: str, schema: dict, model: str,
                      effort: str | None = None) -> dict:
        self.cwd.mkdir(parents=True, exist_ok=True)
        # Claude Code reads project files (CLAUDE.md, .claude/, .mcp.json) from its cwd;
        # the pipeline's cwd must be completely empty.
        found = sorted(p.name for p in self.cwd.iterdir())
        if found:
            raise LLMError(f"{self.cwd} must be empty; found: {', '.join(found)}")
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        try:
            with f:
                f.write(system)
            reason = ""
            for attempt in range(2):
                prompt = user if attempt == 0 else (
                    f"{user}\n\nYour previous reply was not valid: {reason}. "
                    "Reply with JSON matching the schema only."
                )
                out, reason, tail = self._run(prompt, f.name, schema, model, effort)
                if out is not None:
                    return out
            raise LLMError(f"{reason}; stderr: {tail}")
        finally:
            try:
                os.unlink(f.name)
            except FileNotFoundError:
                pass

    def _run(self, user: str, system_path: str, schema: dict, model: str,
             effort: str | None = None):
        argv = [
            self.bin, "-p", "--model", model, "--tools", "",
            "--system-prompt-file", system_path,
            "--setting-sources", "project,local",
            "--no-session-persistence",
            "--output-format", "json",
            "--json-schema", json.dumps(schema),
        ]
        if effort:
            argv += ["--effort", effort]
        try:
            proc = subprocess.run(
                argv, input=user, capture_output=True, text=True, cwd=str(self.cwd),
                env={**os.environ, "CLAUDE_CODE_RETRY_WATCHDOG": "1"}, timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"claude timed out after {self.timeout_s}s") from e
        tail = (proc.stderr or "")[-300:]
        if proc.returncode != 0:
            raise LLMError(f"claude exited {proc.returncode}: {tail}")
        try:
            env = json.loads(proc.stdout)
        except ValueError as e:
            raise LLMError(f"claude printed non-JSON: {tail}") from e
        if not isinstance(env, dict):
            raise LLMError(f"claude printed unexpected JSON: {tail}")
        self._account(env, model)
        so = env.get("structured_output")
        if so is not None and not env.get("is_error"):
            return so, "", tail
        reason = str(env.get("result"))[:300] if env.get("is_error") and env.get("result") else "no structured_output"
        return None, reason, tail
