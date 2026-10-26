# GenAI Observability & SLO Lab

An **offline, reproducible trace analysis and SLO dashboard** for a fictional RAG / agent workflow. Demonstrates reconstruction of parent/child spans, exclusive time under concurrent child spans, token cost estimates, request-level SLIs, and multi-window error-budget burn-rate alerts.

> **Scope:** OpenTelemetry-*inspired* JSON spans, not OTLP, an OpenTelemetry SDK exporter, a managed monitoring service, or a live Gemini/Vertex AI deployment. All 40 traces are simulated.

## What it demonstrates

- **Trace modeling:** span ID, trace ID, parent, operation, start/end timestamps, status, allowlisted attributes.
- **Structural validation:** duplicate IDs, missing parent, parent containment, exactly one request root, invalid duration and operation names are rejected.
- **Time accounting:** overlapping child durations are merged before computing parent *exclusive* time (no double-counting concurrent work).
- **SLIs and objectives:** availability, successful responses within latency threshold, p50/p95 nearest-rank latency, remaining error budget.
- **Two-window budget burn:** short and long time windows with explicit thresholds and empty-window handling.
- **Cost visibility:** synthetic token usage and **fabricated per-model prices** for demonstration; not actual cloud billing.
- **Data minimization:** only a small allowlist of non-sensitive attributes is retained; prompt/response content and access tokens are discarded.
- **Shareable report:** self-contained, offline HTML dashboard with a per-trace summary table, no JavaScript, CDN or network dependencies.

## Quick start

Requires **Python 3.11+** and only the standard library:

```bash
python -m genai_observability analyze
python -m genai_observability report --output report.html
python -m unittest discover -s tests -v
```

Open `report.html` locally in a browser. A checked-in [sample report](examples/report.html) is included for review without running code.

To print deterministic synthetic input as JSON:

```bash
python -m genai_observability generate > /tmp/agent-spans.json
```

## Example outcome

The fixed synthetic dataset has **40 requests / 160 spans**, including four simulated failed requests and four additional slow successful responses. The illustrative metrics are **90% availability**, **80% requests successfully under 1500 ms**, and an intentionally triggered multi-window budget-burn alert. These small-sample values are for demonstrating computation and must not be interpreted as production SLO compliance.

## Why this matters

A cloud support specialist investigating agentic applications needs to distinguish tool latency from model latency, correlate failures with traces, understand reliability objectives and avoid leaking prompt content into diagnostic telemetry. This project makes those concerns executable and testable.

## Architecture

```text
40 synthetic request traces
        |
Validate tree structure -> sanitized spans
        |                  |
        |              exclusive time per span
        +--> request-level SLIs & p95
        +--> synthetic token cost
        +--> short/long error budget burn
                      |
               Static HTML report
```

The trace format follows the *conceptual shape* of [OpenTelemetry spans](https://opentelemetry.io/docs/specs/otel/trace/api/) but does not implement its protocol. The SLO budget/burn approach is a didactic simplification; real alerting requires tuned windows, minimum traffic, proper telemetry sampling, paging policy, and business-specific objectives.

## Limitations and next steps

- No telemetry collector, remote monitoring, cloud credentials or Gemini API calls.
- Complete fabricated trace dataset; no sampling correction or significant statistical inference.
- Pricing is mocked and excludes caching, batch pricing, regional differences, taxes and rounding rules.
- Bottlenecks are based on **largest exclusive span time**, not causal critical-path reconstruction.
- Fixed synthetic timestamps are used for reproducible tests; the synthetic burn alert is not tied to your local time.

Possible extensions: instrument a live mock API with the OpenTelemetry SDK, send OTLP to a local collector, add a trace waterfall UI and build a model/tool-level alert dashboard.
