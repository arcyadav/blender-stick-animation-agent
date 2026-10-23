"""A stick man walks to a bench, sits down, looks up at a tree, sighs, waves at a friend who walks
past, stands up and walks off.  python -m scripts.demo_sit"""
import time

import config
from blender_worker.client import BlenderWorker

OUT = config.OUTPUTS / "demo_sit"


def main():
    t = time.time()
    with BlenderWorker(OUT) as w:
        w.call("scene_reset")
        w.call("add_asset", asset="tree", name="tree", location=[-2.6, 0], layer="back")
        w.call("add_asset", asset="bench", name="bench", location=[0.2, 0], layer="back")
        w.call("add_stick_figure", name="man", location=[-4.5, 0], facing="right")
        w.call("add_stick_figure", name="friend", location=[5.0, 0], facing="left", colour="blue")
        for call in [
                dict(name="man", action="walk", to="bench"),
                dict(name="man", action="sit", to="bench"),
                dict(name="man", action="look", to="tree"),
                dict(name="man", action="sigh"),
                dict(name="friend", action="walk", to=1.6, start_frame=230),
                dict(name="man", action="wave", to="friend", start_frame=320),
                dict(name="friend", action="wave", to="man", start_frame=320),
                dict(name="man", action="stand_up"),
                dict(name="man", action="walk", direction="right", distance=0.5),
                dict(name="man", action="handshake", to="friend", start_frame=440),
                dict(name="friend", action="handshake", to="man", start_frame=440),
                dict(name="friend", action="walk", distance=0.6, direction="right")]:
            r = w.call("play_action", **call)
            print(call["name"], call["action"], r["frames"], r["facing"], r.get("note", ""))
        w.call("set_camera", look_at=[0, 1.5], width=9)
        s = w.call("sample_scene")
        print("collisions:", s["collisions"][:6], "sits:", s["figures"]["man"]["sits"])
        print(w.call("render_final", filename="sit.mp4"))
        w.call("save_blend", filename="sit.blend")
    print("total", round(time.time() - t, 1), "s")


if __name__ == "__main__":
    main()
