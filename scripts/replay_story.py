"""Rebuild a directed story from its logged tool calls (e.g. after a tool fix) and render it again.

    python -m scripts.replay_story outputs/story/ball_that_goes_away_A3
    python -m scripts.replay_story outputs/story/lost_ball --dress      # as simple cartoon characters
    python -m scripts.replay_story outputs/story/ball_that_goes_away_A3 --dress --female man
    python -m scripts.replay_story outputs/story/ball_that_goes_away_A3 --puppet man   # drawn character
"""
import json
import sys
from pathlib import Path

from blender_worker.client import BlenderWorker, ToolError
from blender_worker.schema import validate


def main(story_dir, dress=False, female=(), puppet=()):
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
        if dress:
            for c in log["calls"]:
                if c["tool"] == "add_stick_figure" and not c.get("error"):
                    n = c["args"]["name"]
                    if n in female:
                        w.call("dress_figure", name=n, style="female", outfit={"shirt": "pink", "skirt": "purple"})
                    else:
                        w.call("dress_figure", name=n)
        for n in puppet:
            w.call("puppet_figure", name=n)
        out = "puppet" if puppet else "dressed" if dress else "final"
        print(w.call("render_final", filename=f"{out}.mp4"))
        w.call("save_blend", filename=f"{out}.blend")


if __name__ == "__main__":
    a = sys.argv
    main(a[1], "--dress" in a, a[a.index("--female") + 1].split(",") if "--female" in a else (),
         a[a.index("--puppet") + 1].split(",") if "--puppet" in a else ())
