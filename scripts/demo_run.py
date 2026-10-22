"""A stick man runs for about 6 seconds, the camera following him.  python -m scripts.demo_run"""
import time

import config
from blender_worker.client import BlenderWorker

OUT = config.OUTPUTS / "demo_run"


def main():
    t = time.time()
    with BlenderWorker(OUT) as w:
        w.call("scene_reset")
        # a few trees in the back layer so the running reads against something
        for i, x in enumerate([-2, 4, 10, 16]):
            w.call("add_asset", asset="tree", name=f"tree{i}", location=[x, 0], layer="back")
        print(w.call("add_stick_figure", name="man", location=[-4, 0], facing="right"))
        r = print(w.call("play_action", name="man", action="run", direction="right", seconds=6))
        w.call("set_camera", look_at="man", width=7)
        end = w.call("scene_state")["frames"]["end"]
        print(w.call("camera_move", kind="follow", target="man", start_frame=1, end_frame=end))
        print(w.call("render_final", filename="run.mp4"))
        print(w.call("save_blend", filename="run.blend"))
    print("total", round(time.time() - t, 1), "s", r or "")


if __name__ == "__main__":
    main()
