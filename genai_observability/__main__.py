import argparse
import json
from .core import burn_rates, load_traces, summarize
from .fixtures import ANCHOR_MS, generate, load_fixture
from .report import write_report

parser = argparse.ArgumentParser(description="Analyze fictional agent traces and SLO burn")
parser.add_argument("command", choices=["analyze", "generate", "report"], nargs="?", default="analyze")
parser.add_argument("--output", default="report.html")
args = parser.parse_args()
if args.command == "generate":
    print(json.dumps(generate(), indent=2))
else:
    traces = load_traces(load_fixture())
    if args.command == "report":
        print(write_report(traces, args.output))
    else:
        summary = summarize(traces)
        print(json.dumps({"summary": summary, "burn": burn_rates(summary, ANCHOR_MS)}, indent=2))
