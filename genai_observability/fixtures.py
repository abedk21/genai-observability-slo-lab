"""Deterministically generate 40 fabricated traces, with parallel subspans."""
from __future__ import annotations

import json
from pathlib import Path
from .core import load_traces

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic_spans.json"
ANCHOR_MS = 1_800_000_000_000


def generate(count: int = 40) -> list[dict]:
    if not 1 <= count <= 1000:
        raise ValueError("count outside 1..1000")
    events = []
    for i in range(count):
        tid = f"synthetic-trace-{i:04d}"
        time = ANCHOR_MS - (count - i) * 90_000  # 90 sec spacing, about an hour.
        fail = (i in {10, 32, 37, 39})
        slow = i in {8, 14, 24, 38}
        duration = 2400 if slow else 1080 + (i % 4) * 75
        root = {"trace_id": tid, "span_id": "r", "parent_id": None, "name": "agent.request", "start_ms": time,
                "end_ms": time + duration, "status": "error" if fail else "ok", "attributes": {"cache_hit": i % 3 == 0}}
        retrieve = {"trace_id": tid, "span_id": "s", "parent_id": "r", "name": "retrieval.search", "start_ms": time + 50,
                    "end_ms": time + 260, "status": "ok", "attributes": {"tool": "synthetic-kb"}}
        model = {"trace_id": tid, "span_id": "m", "parent_id": "r", "name": "llm.generate", "start_ms": time + 200,
                 "end_ms": time + duration - 160, "status": "error" if fail else "ok",
                 "attributes": {"model": "mock-small", "input_tokens": 650 + i * 2, "output_tokens": 120 + i}}
        guard = {"trace_id": tid, "span_id": "g", "parent_id": "r", "name": "guardrail.check", "start_ms": time + duration - 145,
                 "end_ms": time + duration - 20, "status": "ok", "attributes": {}}
        events.extend([root, retrieve, model, guard])
    load_traces(events)
    return events


def load_fixture() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))
