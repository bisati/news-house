"""JSON schemas for LLM calls. Later tasks add more."""

from newshouse.catalogue import SLIDE_KINDS, TONES, VISUALS

SAME_EVENT_SCHEMA = {"type": "object", "properties": {"pairs": {"type": "array", "items": {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "same": {"type": "boolean"}}, "required": ["a", "b", "same"]}}}, "required": ["pairs"]}

STORY_TYPES = ["launch", "number", "saga", "debate", "rule_change", "plain", "fixture", "noise"]
_CLASSIFY_FIELDS = {
    "cluster_id": {"type": "string"},
    "story_type": {"type": "string", "enum": STORY_TYPES},
    "topics": {"type": "array", "items": {"type": "string"}},
    "importance": {"type": "integer", "minimum": 0, "maximum": 100},
    "early": {"type": "integer", "minimum": 0, "maximum": 100},
    "reason": {"type": "string"},
    "breaking_eligible": {"type": "boolean"},
    "is_delta": {"type": "boolean"},
    "tone": {"type": "string", "enum": list(TONES)},
}
CLASSIFY_SCHEMA = {"type": "object", "properties": {"results": {"type": "array", "items": {
    "type": "object", "properties": _CLASSIFY_FIELDS, "required": list(_CLASSIFY_FIELDS)}}},
    "required": ["results"]}

THREAD_MATCH_SCHEMA = {"type": "object", "properties": {"matches": {"type": "array", "items": {"type": "object", "properties": {"cluster_id": {"type": "string"}, "thread_id": {"type": ["string", "null"]}}, "required": ["cluster_id", "thread_id"]}}}, "required": ["matches"]}

_SLIDE_FIELDS = {
    "kind": {"type": "string", "enum": list(SLIDE_KINDS)},
    "title": {"type": "string"},
    "body": {"type": "string"},
    "payload": {"type": "object"},
    "highlight": {"type": "boolean"},
}
_WRITE_FIELDS = {
    "visual": {"type": "string", "enum": list(VISUALS)},
    "headline": {"type": "string"},
    "line": {"type": "string"},
    "para": {"type": "string"},
    "brief": {"type": "string"},
    "why": {"type": "string"},
    "cited_item_ids": {"type": "array", "items": {"type": "string"}},
    "payload": {"type": "object"},
    "slides": {"type": "array", "items": {"type": "object", "properties": _SLIDE_FIELDS,
                                          "required": list(_SLIDE_FIELDS)}},
    "tone": {"type": "string", "enum": list(TONES)},
}
WRITE_SCHEMA = {"type": "object", "properties": _WRITE_FIELDS, "required": list(_WRITE_FIELDS)}

STACK_GROUPS_SCHEMA = {"type": "object", "properties": {"groups": {"type": "array", "items": {
    "type": "object", "properties": {"ids": {"type": "array", "items": {"type": "string"}},
                                     "reason": {"type": "string"}},
    "required": ["ids", "reason"]}}}, "required": ["groups"]}

_STACK_LINE_FIELDS = {"cluster_id": {"type": "string"}, "headline": {"type": "string"},
                      "line": {"type": "string"}}
STACK_LINES_SCHEMA = {"type": "object", "properties": {"rows": {"type": "array", "items": {
    "type": "object", "properties": _STACK_LINE_FIELDS, "required": list(_STACK_LINE_FIELDS)}}},
    "required": ["rows"]}
