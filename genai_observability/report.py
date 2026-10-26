"""Static offline diagnostics report: no CDN, scripts, or remote trackers."""
from __future__ import annotations

from html import escape
from pathlib import Path
from .core import burn_rates, summarize, Span
from .fixtures import ANCHOR_MS


def render_html(grouped: dict[str, list[Span]], now_ms: int = ANCHOR_MS) -> str:
    summary = summarize(grouped)
    burn = burn_rates(summary, now_ms=now_ms)
    traces = summary["traces"]
    def pct(v: float | None) -> str:
        return "n/a" if v is None else f"{v * 100:.1f}%"
    rows = "\n".join(
        f"<tr><td>{escape(x['trace_id'])}</td><td>{x['duration_ms']} ms</td>"
        f"<td>{'OK' if x['success'] else 'ERROR'}</td><td>{escape(x['bottleneck'])}</td>"
        f"<td>${x['total_cost_usd']:.6f}</td></tr>" for x in traces
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Synthetic GenAI tracing &amp; SLO report</title>
<style>body{{font:15px system-ui,sans-serif;margin:36px auto;max-width:1100px;padding:0 18px;color:#13263b;background:#f7fafc}}
header{{background:#102b46;color:white;padding:24px;border-radius:14px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}}
.metrics div{{padding:16px;border:1px solid #d7e3ef;border-radius:12px;background:white}}strong{{display:block;font-size:23px;margin:6px 0}}
table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:10px;border-bottom:1px solid #e2e8f0;text-align:left}}th{{background:#edf4fc}}.warn{{font-weight:700;color:#8b2d16}}small{{color:#546579}}
</style></head><body><header><h1>GenAI Observability Lab</h1><p>Offline synthetic traces · Trace waterfalls reconstructed from local JSON · No customer data</p></header>
<section class="metrics"><div>Requests<strong>{summary['requests']}</strong></div><div>Availability<strong>{pct(summary['availability'])}</strong></div>
<div>Good latency<strong>{pct(summary['latency_success_fraction'])}</strong></div><div>p95 latency<strong>{summary['p95_ms']} ms</strong></div><div>Mock token costs<strong>${summary['estimated_cost_usd']:.5f}</strong></div></section>
<p class="{'warn' if burn['alert'] else ''}">Multi-window synthetic burn alert: <b>{'TRIGGERED' if burn['alert'] else 'not triggered'}</b></p>
<p><small>Nearest-rank p95; availability &amp; latency SLIs are request counts. Local simulation with made-up token prices and only 40 requests. No production telemetry SDK or alert paging.</small></p>
<h2>Trace summary</h2><table><thead><tr><th>Trace ID</th><th>Duration</th><th>Result</th><th>Largest exclusive-time operation</th><th>Cost</th></tr></thead><tbody>{rows}</tbody></table></body></html>'''


def write_report(grouped: dict[str, list[Span]], output: str) -> Path:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_html(grouped), encoding="utf-8")
    return target
