"""Rebuild a directed story from its logged tool calls (e.g. after a tool fix) and render it again.

    python -m scripts.replay_story outputs/story/ball_that_goes_away_A3
"""
import json
import sys
from pathlib import Path

from blender_worker.client import BlenderWorker, ToolError
from blender_worker.schema import validate


def main(story_dir):
    d = Path(story_dir)
    log = json.loads((d / "story_log.json").read_text(encoding="utf-8"))
    with BlenderWorker(d) as w:
        w.call("set_output", subdir="")
        w.call("scene_reset")
        for c in log["calls"]:
            if c.get("error") or c["tool"] == "check_scene":
                continue
            try:
                w.call(c["tool"], **validate(c["tool"], c["args"])[0])
            except ToolError as e:
                print("error now:", c["tool"], e)
        for s in log["shots"][1:-1]:                # characters new in a later shot appear when it starts
            for c in log["calls"]:
                if c["shot"] == log["shots"].index(s) + 1 and c["tool"] == "add_stick_figure" and not c.get("error"):
                    w.call("appear_at", name=c["args"]["name"], frame=s["frames"][0] + 1)
        print(w.call("render_final", filename="final.mp4"))
        w.call("save_blend", filename="scene.blend")


if __name__ == "__main__":
    main(sys.argv[1])
