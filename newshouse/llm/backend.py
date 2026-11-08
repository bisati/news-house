"""LLM backend protocol and factory."""
from __future__ import annotations

from typing import Protocol


class LLMError(Exception):
    """Raised when a backend cannot produce a valid JSON reply."""


class LLMBackend(Protocol):
    usage: dict[str, dict]

    def complete_json(self, *, system: str, user: str, schema: dict, model: str,
                      effort: str | None = None) -> dict: ...

    def snapshot(self) -> dict[str, dict]: ...

    def reset(self) -> None: ...


def cheap_effort(model: str) -> str | None:
    """Every Haiku call (same-event, classify, thread-match) runs at low effort."""
    return "low" if model == "haiku" else None


USAGE_FIELDS = ("calls", "input", "cache_read", "cache_create", "output", "cost", "turns", "api_ms")


def empty_usage() -> dict:
    return {k: 0 for k in USAGE_FIELDS}


def snapshot_of(backend) -> dict[str, dict]:
    """The backend's cumulative usage, or {} for backends (or test stubs) without one."""
    snap = getattr(backend, "snapshot", None)
    return snap() if callable(snap) else {}


def usage_delta(before: dict[str, dict], after: dict[str, dict]) -> dict[str, dict]:
    """Per-model difference of two snapshots; models with no new calls are dropped."""
    out: dict[str, dict] = {}
    for model, a in after.items():
        b = before.get(model, {})
        d = {k: a.get(k, 0) - b.get(k, 0) for k in USAGE_FIELDS}
        if d["calls"]:
            d["cost"] = round(d["cost"], 6)
            out[model] = d
    return out


def get_backend(settings) -> LLMBackend:
    kind = settings.llm_backend
    if kind == "claude-code":
        from newshouse.llm.claude_code import ClaudeCodeBackend

        return ClaudeCodeBackend(settings.claude_bin, settings.claude_cwd)
    if kind == "fake":
        from newshouse.llm.fake import FakeBackend

        return FakeBackend([])
    if kind == "api":
        raise NotImplementedError("api backend is phase 3")
    raise ValueError(f"unknown llm_backend: {kind}")
