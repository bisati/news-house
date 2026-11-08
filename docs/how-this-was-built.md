# How this was built

News House was built with an agent workflow, documented here so the process is as inspectable as the code.

## The process

1. Brainstorm in conversation.
2. Write the design spec (`docs/design.md`).
3. Builder check: a fresh agent reads the spec cold and flags gaps.
4. Write the implementation plan (`docs/plan-a.md`).
5. Subagent-driven development: each task is implemented by a fresh implementer agent and checked by a fresh reviewer agent before the next task starts.
6. A whole-branch review at the end.

Work happens on branch `build/plan-a`, pushed after every task. `main` is production.

## LLM roles inside the product

| Role | Prompt file |
|---|---|
| Same-event confirmer | `newshouse/llm/prompts/same_event.system.md` |
| Classifier | `newshouse/llm/prompts/classify.system.md` |
| Thread matcher | `newshouse/llm/prompts/thread_match.system.md` |
| Card writer | `newshouse/llm/prompts/write.system.md` (with `house_style.md`) |

## Build log

Per-task summaries, reviewer verdicts and follow-ups are in `docs/build-log.md`.
