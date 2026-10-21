"""Run an agent on tasks.json and check every result.

    python eval.py --agent A0 --category static_layout,object_motion
    python eval.py --agent A0 --ids m01,m02 --render        # also renders check frames + a Workbench MP4
"""
import argparse
import json
import time

import config
from agent.template import Template
from blender_worker.client import BlenderWorker, ToolError
from checks.checker import check_task, report_text

AGENTS = {"A0": Template}


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
    try:
        agent.run(task["request"], w, log=lambda tool, args, r: log.append({"tool": tool, "args": args}))
    except ToolError as e:
        error = str(e)
    secs = time.time() - t0
    sample = w.call("sample_scene")
    report = check_task(task, sample, defaults)
    out = {"id": task["id"], "category": task["category"], "request": task["request"], "agent": agent.name,
           "passed": report["passed"] and error is None, "error": error, "seconds": round(secs, 1),
           "tool_calls": len(log), "report": report, "calls": log}
    if render:
        n = sample["end"] - sample["start"]
        w.call("render_check", frames=[sample["start"], sample["start"] + n // 2, sample["end"]])
        w.call("render_final", engine="workbench", filename="final.mp4")
        w.call("save_blend", filename="scene.blend")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="A0", choices=AGENTS)
    ap.add_argument("--ids")
    ap.add_argument("--category")
    ap.add_argument("--render", action="store_true")
    a = ap.parse_args()
    tasks, defaults = load_tasks(a.ids and a.ids.split(","), a.category and a.category.split(","))
    agent = AGENTS[a.agent]()
    out_dir = config.OUTPUTS / "eval" / a.agent
    results = []
    with BlenderWorker(out_dir) as w:
        for t in tasks:
            r = run_task(agent, t, defaults, w, render=a.render)
            results.append(r)
            (out_dir / t["id"] / "result.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"{mark} {t['id']:4} {r['seconds']:5.1f}s  {t['request']}")
            if not r["passed"]:
                print("     " + (r["error"] or report_text(r["report"])).replace("\n", "\n     "))
    n = sum(r["passed"] for r in results)
    print(f"\n{a.agent}: {n}/{len(results)} tasks passed")
    summary = {"agent": a.agent, "passed": n, "total": len(results),
               "tasks": [{k: r[k] for k in ("id", "category", "passed", "seconds", "tool_calls")} for r in results]}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
