"""Task p01 built by hand: a stick man walks to the table and waves.  python -m scripts.demo_figure"""
import json
import time

import config
from blender_worker.client import BlenderWorker

OUT = config.OUTPUTS / "demo_figure"


def main():
    t = time.time()
    with BlenderWorker(OUT) as w:
        w.call("scene_reset")
        print(w.call("add_asset", asset="tree", name="tree", location=[-3.2, 0], layer="back"))
        print(w.call("add_asset", asset="table", name="table", location=[2.2, 0]))
        print(w.call("add_primitive", type="sphere", name="ball", location={"on_top_of": "table"}, size=0.18,
                     colour="red"))
        print(w.call("add_stick_figure", name="man", location=[-2.5, 0], facing="right"))
        print(w.call("play_action", name="man", action="walk", to="table"))
        print(w.call("play_action", name="man", action="wave"))
        print(w.call("set_camera", look_at=[0, 1.6], width=8.5))
        print(json.dumps(w.call("scene_state"))[:900])
        s = w.call("sample_scene")
        print("collisions:", s["collisions"][:5], "frames:", len(s["frames"]))
        n = s["end"]
        print(w.call("render_check", frames=[1, 30, 60, 100, 140, n]))
        print(w.call("render_final", filename="figure.mp4"))
        print(w.call("save_blend", filename="figure.blend"))
    print("total", round(time.time() - t, 1), "s")


if __name__ == "__main__":
    main()
