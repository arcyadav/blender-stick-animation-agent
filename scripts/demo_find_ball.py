"""A stick man walks along, stops, looks down at a ball on the ground, picks it up and walks on
carrying it; the camera follows him.

    python -m scripts.demo_find_ball                 # holds it up in front
    python -m scripts.demo_find_ball swing           # carries it at his side, swinging with the walk
"""
import sys
import time

import config
from blender_worker.client import BlenderWorker

OUT = config.OUTPUTS / "demo_find_ball"


def main(carry="front"):
    t = time.time()
    with BlenderWorker(OUT) as w:
        w.call("scene_reset")
        for i, x in enumerate([-3.5, 2.5, 8.5]):
            w.call("add_asset", asset="tree", name=f"tree{i}", location=[x, 0], layer="back")
        print(w.call("add_primitive", type="sphere", name="ball", location=[1.0, 0], size=0.18, colour="red"))
        print(w.call("add_stick_figure", name="man", location=[-3.0, 0], facing="right"))
        print(w.call("play_action", name="man", action="walk", to="ball"))
        print(w.call("play_action", name="man", action="look_down", to="ball", seconds=1.6))
        print(w.call("play_action", name="man", action="pick_up", to="ball", carry=carry))
        print(w.call("play_action", name="man", action="walk", direction="right", distance=3.5))
        w.call("set_camera", look_at="man", width=6.5)
        end = w.call("scene_state")["frames"]["end"]
        print(w.call("camera_move", kind="follow", target="man", start_frame=1, end_frame=end))
        s = w.call("sample_scene")
        print("holds:", s["figures"]["man"]["holds"])
        print(w.call("render_final", filename=f"find_ball_{carry}.mp4"))
        print(w.call("save_blend", filename=f"find_ball_{carry}.blend"))
    print("total", round(time.time() - t, 1), "s")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "front")
