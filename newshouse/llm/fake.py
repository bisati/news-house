"""Deterministic backend for tests."""
from __future__ import annotations

import copy
from typing import Callable

from newshouse.llm.backend import LLMError, empty_usage


class FakeBackend:
    def __init__(self, responses: list[dict] | Callable[[str, str, dict, str], dict]):
        self._responses = responses
        self.calls: list[dict] = []
        self.usage: dict[str, dict] = {}

    def complete_json(self, *, system: str, user: str, schema: dict, model: str,
                      effort: str | None = None) -> dict:
        self.calls.append({"system": system, "user": user, "schema": schema, "model": model,
                           "effort": effort})
        self.usage.setdefault(model, empty_usage())["calls"] += 1  # tokens stay zero
        if callable(self._responses):
            return self._responses(system, user, schema, model)
        if not self._responses:
            raise LLMError("fake backend exhausted")
        return self._responses.pop(0)

    def snapshot(self) -> dict[str, dict]:
        return copy.deepcopy(self.usage)

    def reset(self) -> None:
        self.usage = {}
