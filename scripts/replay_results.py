"""Rebuild each saved run in Blender from its logged tool calls, check it again and render its clip.

The eval runs without rendering; this replays every call that worked, in order, so the clip shows
exactly the scene the agent built. The check is re-run and must give the same pass/fail.

    python -m scripts.replay_results results/final_2026-10-25 A0,A3
"""
import json
import sys
import time
from pathlib import Path

import config
from blender_worker.client import BlenderWorker, ToolError
from blender_worker.schema import validate
from checks.checker import check_task

CLIPS = config.OUTPUTS / "replays"


def replay(w, result):
    w.call("scene_reset")
    for c in result["calls"]:
        if c.get("error") or c["tool"] == "check_scene":     # a logged scene_reset wiped the scene: keep it
            continue
        try:
            w.call(c["tool"], **validate(c["tool"], c["args"])[0])    # as the agent did: {x, z} -> [x, z]
        except ToolError:
            pass


def main(root, agents):
    tasks = {t["id"]: t for t in json.loads((config.ROOT / "tasks.json").read_text(encoding="utf-8"))["tasks"]}
    defaults = json.loads((config.ROOT / "tasks.json").read_text(encoding="utf-8"))["defaults"]["checks"]
    for agent in agents:
        out = CLIPS / agent
        same = 0
        files = sorted((Path(root) / agent).glob("*/result.json"))
        with BlenderWorker(out) as w:
            for f in files:
                r = json.loads(f.read_text(encoding="utf-8"))
                t = time.time()
                w.call("set_output", subdir="")
                replay(w, r)
                rep = check_task(tasks[r["id"]], w.call("sample_scene"), defaults)
                again = rep["passed"] and not r.get("error")
                same += again == r["passed"]
                try:
                    w.call("render_final", filename=f"{r['id']}.mp4")
                except ToolError as e:                       # e.g. an empty scene with no camera
                    print("   no clip:", e)
                print(f"{agent} {r['id']}: recorded {'PASS' if r['passed'] else 'FAIL'}, replay "
                      f"{'PASS' if again else 'FAIL'}  {time.time() - t:.0f} s", flush=True)
        print(f"{agent}: replay matches the recorded result for {same}/{len(files)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1], sys.argv[2].split(","))
