"""Stick figures dressed as simple cartoon characters (a look on the same motion).

    python -m scripts.demo_costume
"""
import time

import config
from blender_worker.client import BlenderWorker

OUT = config.OUTPUTS / "demo_costume"


def main():
    t = time.time()
    with BlenderWorker(OUT) as w:
        w.call("scene_reset")
        w.call("add_asset", asset="bench", name="bench", location=[1.5, 0], layer="back")
        w.call("add_asset", asset="tree", name="tree", location=[-2.8, 0], layer="back")
        w.call("add_stick_figure", name="red", location=[-3.5, 0], facing="right", colour="red")
        w.call("add_stick_figure", name="blue", location=[4.2, 0], facing="left", colour="blue")
        w.call("play_action", name="red", action="walk_happy", to=-0.6)
        w.call("play_action", name="blue", action="walk_sad", to="bench", start_frame=1)
        w.call("play_action", name="blue", action="sit", to="bench", direction="front")
        w.call("play_action", name="red", action="wave", to="blue")
        w.call("play_action", name="red", action="react")
        w.call("play_action", name="blue", action="look", to="red")
        w.call("play_action", name="red", action="turn", direction="front")
        w.call("play_action", name="red", action="wave")
        w.call("set_camera", look_at=[0.3, 1.4], width=9)
        print(w.call("dress_figure", name="red"))
        print(w.call("dress_figure", name="blue", outfit={"trousers": "grey", "hair": "black"}))
        print(w.call("render_final", filename="costume.mp4"))
    print("total", round(time.time() - t, 1), "s")


if __name__ == "__main__":
    main()
