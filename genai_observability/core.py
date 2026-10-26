"""Offline trace reconstruction and SLIs for synthetic GenAI workflows.

The input resembles trace/span concepts from OpenTelemetry, but is NOT OTLP.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Any

ALLOWED_ATTRS = frozenset({"model", "tool", "input_tokens", "output_tokens", "retry", "cache_hit"})
PRICE_PER_MILLION = {"mock-small": (0.10, 0.40), "mock-large": (0.80, 2.50)}


class InvalidTrace(ValueError):
    pass


@dataclass(frozen=True)
class Span:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    start_ms: int
    end_ms: int
    status: str
    attributes: dict[str, Any]

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def safe_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Allowlist only explicitly non-sensitive fields, ignore prompts and token text."""
    if not isinstance(attrs, dict):
        raise InvalidTrace("attributes must be an object")
    result = {}
    for key in ALLOWED_ATTRS:
        if key not in attrs:
            continue
        val = attrs[key]
        if key in {"input_tokens", "output_tokens", "retry"}:
            if type(val) is not int or val < 0 or val > 10_000_000:
                raise InvalidTrace(f"invalid numeric attribute: {key}")
        elif key == "cache_hit":
            if type(val) is not bool:
                raise InvalidTrace("cache_hit must be boolean")
        else:
            if not isinstance(val, str) or len(val) > 60 or any(ord(c) < 32 for c in val):
                raise InvalidTrace(f"invalid string attribute: {key}")
        result[key] = val
    return result


def load_traces(rows: list[dict[str, Any]]) -> dict[str, list[Span]]:
    """Validate every parent link and timeframe before computing trace metrics."""
    grouped: dict[str, list[Span]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    if not isinstance(rows, list):
        raise InvalidTrace("expected list of spans")
    for r in rows:
        if not isinstance(r, dict):
            raise InvalidTrace("span must be an object")
        ids = (r.get("trace_id"), r.get("span_id"))
        if (not isinstance(ids[0], str) or not ids[0].isascii() or not 2 <= len(ids[0]) <= 64 or
                not isinstance(ids[1], str) or not ids[1].isascii() or not 1 <= len(ids[1]) <= 64):
            raise InvalidTrace("invalid trace/span id")
        if ids in seen:
            raise InvalidTrace("duplicate span")
        seen.add(ids)
        start, end = r.get("start_ms"), r.get("end_ms")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise InvalidTrace("invalid timestamps")
        name = r.get("name")
        if name not in {"agent.request", "llm.generate", "tool.call", "retrieval.search", "guardrail.check"}:
            raise InvalidTrace("unexpected operation")
        status = r.get("status")
        if status not in {"ok", "error"}:
            raise InvalidTrace("invalid status")
        parent = r.get("parent_id")
        if parent is not None and (not isinstance(parent, str) or not parent):
            raise InvalidTrace("invalid parent")
        grouped[ids[0]].append(Span(ids[0], ids[1], parent, name, start, end, status, safe_attrs(r.get("attributes", {}))))
    for tid, spans in grouped.items():
        by_id = {s.span_id: s for s in spans}
        roots = [s for s in spans if s.parent_id is None]
        if len(roots) != 1 or roots[0].name != "agent.request":
            raise InvalidTrace(f"trace {tid}: expected one request root")
        for span in spans:
            if span.parent_id is None:
                continue
            parent = by_id.get(span.parent_id)
            if parent is None or not (parent.start_ms <= span.start_ms < span.end_ms <= parent.end_ms):
                raise InvalidTrace(f"trace {tid}: invalid parent timeframe")
            visited = {span.span_id}
            walk = parent
            while walk is not None:
                if walk.span_id in visited:
                    raise InvalidTrace("cycle")
                visited.add(walk.span_id)
                walk = by_id.get(walk.parent_id) if walk.parent_id is not None else None
        grouped[tid].sort(key=lambda x: (x.start_ms, x.span_id))
    return dict(sorted(grouped.items()))


def percentile_nearest_rank(data: list[int], pct: float) -> int | None:
    if not data:
        return None
    if not 0 < pct <= 1:
        raise ValueError("percentile outside 0..1")
    values = sorted(data)
    return values[math.ceil(len(values) * pct) - 1]


def merged_duration(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    intervals = sorted(intervals)
    start, end = intervals[0]
    total = 0
    for s, e in intervals[1:]:
        if s <= end:
            end = max(end, e)
        else:
            total += end - start
            start, end = s, e
    return total + end - start


def self_times(spans: list[Span]) -> dict[str, int]:
    children: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for s in spans:
        if s.parent_id is not None:
            children[s.parent_id].append((s.start_ms, s.end_ms))
    return {s.span_id: s.duration_ms - merged_duration(children[s.span_id]) for s in spans}


def trace_cost_usd(spans: list[Span]) -> float:
    value = 0.0
    for span in spans:
        if span.name != "llm.generate":
            continue
        model = span.attributes.get("model", "mock-small")
        if model not in PRICE_PER_MILLION:
            raise InvalidTrace("unknown simulated pricing model")
        ir, orate = PRICE_PER_MILLION[model]
        value += (span.attributes.get("input_tokens", 0) * ir +
                  span.attributes.get("output_tokens", 0) * orate) / 1_000_000
    return round(value, 8)


def summarize(grouped: dict[str, list[Span]], latency_target_ms: int = 1500,
              availability_objective: float = 0.99, latency_objective: float = 0.95) -> dict:
    if latency_target_ms <= 0 or not (0 < availability_objective < 1) or not (0 < latency_objective < 1):
        raise ValueError("invalid SLO config")
    results = []
    for tid, spans in grouped.items():
        root = next(x for x in spans if x.parent_id is None)
        own = self_times(spans)
        # Top self-time identifies where latency was actually spent, accounting for parallel children.
        bottleneck = max(spans, key=lambda x: (own[x.span_id], x.span_id))
        results.append({"trace_id": tid, "start_ms": root.start_ms, "duration_ms": root.duration_ms,
                        "success": root.status == "ok", "within_latency_target": root.status == "ok" and root.duration_ms <= latency_target_ms,
                        "total_cost_usd": trace_cost_usd(spans), "bottleneck": bottleneck.name,
                        "bottleneck_self_ms": own[bottleneck.span_id], "span_count": len(spans)})
    n = len(results)
    good = sum(x["success"] for x in results)
    good_latency = sum(x["within_latency_target"] for x in results)
    availability = good / n if n else None
    latency_good_fraction = good_latency / n if n else None
    return {"requests": n, "availability": availability, "availability_target": availability_objective,
            "latency_success_fraction": latency_good_fraction, "latency_success_target": latency_objective,
            "latency_threshold_ms": latency_target_ms,
            "p50_ms": percentile_nearest_rank([x["duration_ms"] for x in results], 0.50),
            "p95_ms": percentile_nearest_rank([x["duration_ms"] for x in results], 0.95),
            "estimated_cost_usd": round(sum(x["total_cost_usd"] for x in results), 8),
            "availability_budget_remaining_requests": max(0.0, n * (1 - availability_objective) - (n - good)),
            "traces": sorted(results, key=lambda x: (x["start_ms"], x["trace_id"]))}


def burn_rates(summary: dict, now_ms: int, objective: float = 0.99,
               short_minutes: int = 5, long_minutes: int = 60, threshold: float = 2) -> dict:
    """Rolling-window availability budget burn, demonstration not a paging policy."""
    if not 0 < objective < 1 or short_minutes <= 0 or long_minutes < short_minutes or threshold <= 0:
        raise ValueError("invalid alert parameters")
    traces = summary["traces"]
    def window(minutes: int) -> dict:
        rows = [x for x in traces if now_ms - minutes * 60_000 <= x["start_ms"] <= now_ms]
        violations = sum(not x["success"] for x in rows)
        return {"minutes": minutes, "requests": len(rows), "violations": violations,
                "burn_rate": (violations / len(rows) / (1 - objective)) if rows else None}
    short = window(short_minutes)
    long = window(long_minutes)
    return {"short_window": short, "long_window": long, "threshold": threshold,
            "alert": bool(short["requests"] and long["requests"] and
                          short["burn_rate"] >= threshold and long["burn_rate"] >= threshold)}
