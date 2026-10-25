"""Comparison tables from outputs/eval/<agent>/*/result.json (markdown, for the report).

    python -m scripts.results                 # all agents found
    python -m scripts.results A0 A1 A2 A3
    P5_EVAL=results/final_2026-10-25 python -m scripts.results A0 A1 A2 A3     # a saved run
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import config

EVAL = Path(os.environ.get("P5_EVAL") or config.OUTPUTS / "eval")
CATS = ["static_layout", "object_motion", "figure_single", "figure_sequence", "figure_props", "two_figures_camera"]


def load(agent):
    d = EVAL / agent
    out = []
    for p in sorted(d.glob("*/result.json")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def main(agents):
    sys.stdout.reconfigure(encoding="utf-8")
    rows = {a: load(a) for a in agents}
    rows = {a: r for a, r in rows.items() if r}
    print("| agent | tasks | pass (after fixes) | pass first try | tool calls / task | invalid calls | "
          "tool errors | s / task |")
    print("|---|---|---|---|---|---|---|---|")
    for a, rs in rows.items():
        n = len(rs)
        calls = sum(r["tool_calls"] for r in rs)
        print(f"| {a} | {n} | {sum(r['passed'] for r in rs)} ({pct(sum(r['passed'] for r in rs), n)}) | "
              f"{sum(r.get('passed_first', r['passed']) for r in rs)} | {calls / n:.1f} | "
              f"{pct(sum(r.get('invalid_calls', 0) for r in rs), calls)} | "
              f"{pct(sum(r.get('tool_errors', 0) for r in rs), calls)} | "
              f"{sum(r['seconds'] for r in rs) / n:.0f} |")
    print("\n| category | " + " | ".join(rows) + " |")
    print("|---|" + "---|" * len(rows))
    for c in CATS:
        cells = []
        for a, rs in rows.items():
            sub = [r for r in rs if r["category"] == c]
            cells.append(f"{sum(r['passed'] for r in sub)}/{len(sub)}" if sub else "-")
        print(f"| {c} | " + " | ".join(cells) + " |")
    print("\nMost common failing checks:")
    for a, rs in rows.items():
        fails = defaultdict(int)
        for r in rs:
            for x in r["report"]["results"]:
                if not x["ok"]:
                    fails[x["check"]] += 1
        top = sorted(fails.items(), key=lambda kv: -kv[1])[:6]
        print(f"- {a}: " + (", ".join(f"{k} ×{v}" for k, v in top) or "none"))


if __name__ == "__main__":
    found = sorted(p.name for p in EVAL.iterdir() if p.is_dir())
    main(sys.argv[1:] or found)
