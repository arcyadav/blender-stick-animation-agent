"""A drawn cut-out character on the stick figure's motion (assets/girl).

    python -m scripts.demo_puppet
"""
import time

import config
from blender_worker.client import BlenderWorker

OUT = config.OUTPUTS / "demo_puppet"


def main():
    t = time.time()
    with BlenderWorker(OUT) as w:
        w.call("scene_reset")
        w.call("add_asset", asset="tree", name="tree", location=[2.5, 0], layer="back")
        w.call("add_primitive", type="sphere", name="ball", location=[1.2, 0], size=0.25, colour="red")
        w.call("add_stick_figure", name="girl", location=[-3.0, 0], facing="right")
        w.call("play_action", name="girl", action="walk_happy", to="ball")
        w.call("play_action", name="girl", action="look_down", to="ball")
        w.call("play_action", name="girl", action="walk", direction="left", distance=1.5)
        w.call("play_action", name="girl", action="turn", direction="front")
        w.call("play_action", name="girl", action="wave")
        w.call("play_action", name="girl", action="idle", seconds=1.0)
        w.call("set_camera", look_at=[0.0, 1.0], width=7.5)
        print(w.call("puppet_figure", name="girl"))
        print(w.call("render_final", filename="puppet.mp4"))
    print("total", round(time.time() - t, 1), "s")


if __name__ == "__main__":
    main()
