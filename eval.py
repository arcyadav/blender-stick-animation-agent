"""Run an agent on tasks.json and check every result.

    python eval.py --agent A0 --category static_layout,object_motion
    python eval.py --agent A0 --ids m01,m02 --render        # also renders check frames + an MP4
    python eval.py --agent A1 --ids f01 --fix-rounds 0       # an LLM agent, no fix loop
"""
import argparse
import json
import sys
import time

import config
from agent.claude_agent import ClaudeAgent
from agent.llm_agent import LLMAgent
from agent.template import Template
from blender_worker.client import BlenderWorker, ToolError
from checks.checker import check_task, report_text

AGENTS = {"A0": lambda a: Template(),
          "A1": lambda a: LLMAgent("qwen2.5:3b", "A1", fix_rounds=a.fix_rounds),
          "A2": lambda a: LLMAgent("qwen2.5:7b", "A2", fix_rounds=a.fix_rounds),
          "A3": lambda a: ClaudeAgent("A3", fix_rounds=a.fix_rounds)}


def load_tasks(ids=None, categories=None):
    data = json.loads((config.ROOT / "tasks.json").read_text(encoding="utf-8"))
    tasks = [t for t in data["tasks"]
             if (not ids or t["id"] in ids) and (not categories or t["category"] in categories)]
    return tasks, data["defaults"]["checks"]


def run_task(agent, task, defaults, w, render=False):
    w.call("set_output", subdir=task["id"])
    log = []
    t0 = time.time()
    error = None
    stats = {}

    def check():
        rep = check_task(task, w.call("sample_scene"), defaults)
        return rep["passed"], report_text(rep)

    try:
        out = agent.run(task["request"], w, log=lambda tool, args, err: log.append(
            {"tool": tool, "args": args, **({"error": err} if err else {})}), check=check, task_id=task["id"])
        stats = out if isinstance(out, dict) else {}
    except ToolError as e:
        error = str(e)
    except Exception as e:  # an agent crash (e.g. the LLM server) is recorded, not fatal for the run
        error = f"{type(e).__name__}: {e}"
    secs = time.time() - t0
    sample = w.call("sample_scene")
    report = check_task(task, sample, defaults)
    rounds = stats.get("rounds", [])
    ok = report["passed"] and error is None
    out = {"id": task["id"], "category": task["category"], "request": task["request"], "agent": agent.name,
           "passed": ok, "error": error, "seconds": round(secs, 1),
           "passed_first": rounds[0]["passed"] if rounds else ok,
           "fix_rounds_used": max(0, len(rounds) - 1),
           "tool_calls": stats.get("tool_calls", len(log)), "invalid_calls": stats.get("invalid", 0),
           "tool_errors": stats.get("tool_errors", 0), "llm_seconds": round(stats.get("llm_seconds", 0), 1),
           "stopped": stats.get("stopped"), "report": report, "calls": log,
           "rounds": [{k: r[k] for k in ("passed", "report", "tool_calls")} for r in rounds]}
    if stats.get("transcript"):
        out["transcript"] = stats["transcript"]
    if render:
        n = sample["end"] - sample["start"]
        w.call("render_check", frames=[sample["start"], sample["start"] + n // 2, sample["end"]])
        w.call("render_final", filename="final.mp4")
        w.call("save_blend", filename="scene.blend")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="A0", choices=AGENTS)
    ap.add_argument("--ids")
    ap.add_argument("--category")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--fix-rounds", type=int, default=3)
    ap.add_argument("--tag", default="", help="suffix for the output folder, e.g. 'nofix'")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    tasks, defaults = load_tasks(a.ids and a.ids.split(","), a.category and a.category.split(","))
    agent = AGENTS[a.agent](a)
    name = a.agent + (f"_{a.tag}" if a.tag else "")
    out_dir = config.OUTPUTS / "eval" / name
    results = []
    with BlenderWorker(out_dir) as w:
        for t in tasks:
            r = run_task(agent, t, defaults, w, render=a.render)
            results.append(r)
            (out_dir / t["id"] / "result.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
            mark = "PASS" if r["passed"] else "FAIL"
            fixed = " (after fixing)" if r["passed"] and not r["passed_first"] else ""
            print(f"{mark} {t['id']:4} {r['seconds']:6.1f}s {r['tool_calls']:3} calls "
                  f"{r['invalid_calls']:2} invalid{fixed}  {t['request']}", flush=True)
            if not r["passed"]:
                print("     " + (r["error"] or report_text(r["report"])).replace("\n", "\n     "), flush=True)
    n = sum(r["passed"] for r in results)
    n1 = sum(r["passed_first"] for r in results)
    print(f"\n{name}: {n}/{len(results)} passed ({n1} on the first try)")
    summary = {"agent": name, "passed": n, "passed_first": n1, "total": len(results),
               "tasks": [{k: r[k] for k in ("id", "category", "passed", "passed_first", "fix_rounds_used",
                                            "seconds", "tool_calls", "invalid_calls", "tool_errors")}
                         for r in results]}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
