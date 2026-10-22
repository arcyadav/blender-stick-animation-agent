"""A stick man walks to a table, picks up the ball, carries it to a box and puts it down there.

    python -m scripts.demo_pick
"""
import time

import config
from blender_worker.client import BlenderWorker

OUT = config.OUTPUTS / "demo_pick"


def main():
    t = time.time()
    with BlenderWorker(OUT) as w:
        w.call("scene_reset")
        print(w.call("add_asset", asset="table", name="table", location=[1.8, 0], layer="back"))
        print(w.call("add_primitive", type="sphere", name="ball", location={"on_top_of": "table"}, size=0.18,
                     colour="red"))
        print(w.call("add_asset", asset="box", name="box", location=[-2.6, 0], layer="back"))
        print(w.call("add_stick_figure", name="man", location=[-1.0, 0], facing="right"))
        print(w.call("play_action", name="man", action="walk", to="ball"))
        print(w.call("play_action", name="man", action="pick_up", to="ball"))
        print(w.call("play_action", name="man", action="walk", to="box"))
        print(w.call("play_action", name="man", action="put_down", to="box"))
        print(w.call("play_action", name="man", action="wave"))
        print(w.call("set_camera", look_at=[-0.3, 1.5], width=7.5))
        s = w.call("sample_scene")
        print("collisions:", s["collisions"][:6], "holds:", s["figures"]["man"]["holds"])
        print(w.call("render_final", filename="pick.mp4"))
        print(w.call("save_blend", filename="pick.blend"))
    print("total", round(time.time() - t, 1), "s")


if __name__ == "__main__":
    main()
