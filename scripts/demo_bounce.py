"""Task m01 built by hand through the tools: a red ball bounces three times on the floor.

    python -m scripts.demo_bounce
"""
import json
import time

import config
from blender_worker.client import BlenderWorker, ToolError

OUT = config.OUTPUTS / "demo_bounce"

# (frame, x, height of the ball's bottom): drop from 1.5 m, three bounces losing height
KEYS = [(1, -3.0, 1.5), (13, -2.0, 0.0), (25, -1.2, 0.9), (35, -0.4, 0.0),
        (44, 0.3, 0.5), (51, 0.9, 0.0), (57, 1.3, 0.2), (62, 1.6, 0.0)]


def main():
    t = time.time()
    with BlenderWorker(OUT) as w:
        print("worker up in", round(time.time() - t, 1), "s")
        w.call("scene_reset")
        print(w.call("add_primitive", type="sphere", name="ball", location=[-3, 1.5], size=0.5, colour="red"))
        for f, x, z in KEYS:
            w.call("keyframe", name="ball", property="location", frame=f, value=[x, z])
        print(w.call("set_easing", name="ball", property="location", interpolation="gravity"))
        print(w.call("set_frames", start=1, end=72, fps=24))
        print(w.call("set_camera", look_at=[-0.7, 1.2], width=6.5))

        try:
            w.call("set_transform", name="table", location=[0, 0])
        except ToolError as e:
            print("expected error ->", e)

        print(json.dumps(w.call("scene_state"), indent=1))
        print(w.call("render_check", frames=[1, 13, 25, 35]))
        print(w.call("render_final", filename="bounce.mp4"))
        print(w.call("save_blend", filename="bounce.blend"))
    print("total", round(time.time() - t, 1), "s")


if __name__ == "__main__":
    main()
