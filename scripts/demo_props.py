"""All six props in a row, a ball on the table, an orbiting camera.  python -m scripts.demo_props"""
import json

import config
from blender_worker.client import BlenderWorker

OUT = config.OUTPUTS / "demo_props"


def main():
    with BlenderWorker(OUT) as w:
        w.call("scene_reset")
        for i, a in enumerate(["table", "chair", "bench", "box", "lamp", "tree"]):
            print(w.call("add_asset", asset=a, name=a, location=[-5 + 2 * i, 0, 0]))
        print(w.call("add_primitive", type="sphere", name="ball", location={"on_top_of": "table"}, size=0.25,
                     colour="red"))
        print(w.call("add_asset", asset="lamp", name="desk_lamp", location={"on_top_of": "bench"}))
        print(w.call("set_camera", location=[0, -11, 3], look_at=[0, 0, 0.8]))
        print(w.call("render_check", frames=[1]))
        print(w.call("camera_move", kind="orbit", target="table", degrees=90))
        print(w.call("render_check", frames=[36, 72]))
        s = w.call("sample_scene")
        print("sample:", len(json.dumps(s)) // 1024, "KB; collisions:", s["collisions"][:5])
        ball = s["objects"]["ball"]["frames"][0]
        print("ball lo z:", ball["lo"][2], "visible:", ball["visible"], "screen:", ball["screen"])
        print(json.dumps(w.call("scene_state"))[:600])


if __name__ == "__main__":
    main()
