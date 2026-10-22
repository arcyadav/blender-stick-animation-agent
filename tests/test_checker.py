"""The checker must FAIL broken scenes, naming the right check.  python -m tests.test_checker"""
import json
import sys

import config
from blender_worker.client import BlenderWorker
from checks.checker import check_task

TASKS = {t["id"]: t for t in json.loads((config.ROOT / "tasks.json").read_text(encoding="utf-8"))["tasks"]}
DEFAULTS = json.loads((config.ROOT / "tasks.json").read_text(encoding="utf-8"))["defaults"]["checks"]


def bounce(w, n):
    w.call("add_primitive", type="sphere", name="ball", location=[0, 0, 1.5], size=0.5, colour="red")
    f, h = 1, 1.5
    w.call("keyframe", name="ball", property="location", frame=f, value=[0, 0, h])
    for _ in range(n):
        f += 12
        w.call("keyframe", name="ball", property="location", frame=f, value=[0, 0, 0])
        f += 10
        w.call("keyframe", name="ball", property="location", frame=f, value=[0, 0, 0.6])
    w.call("keyframe", name="ball", property="location", frame=f + 10, value=[0, 0, 0])
    w.call("set_frames", start=1, end=f + 20)
    w.call("set_camera", look_at=[0, 1.2], width=6)


def table_and_ball(w, ball_loc):
    w.call("add_asset", asset="table", name="table", location=[0, 0, 0])
    w.call("add_primitive", type="sphere", name="ball", location=ball_loc, size=0.18, colour="red")
    w.call("add_asset", asset="chair", name="chair", location={"next_to": "table"})


def row(w, colours):
    for i, c in enumerate(colours):
        w.call("add_primitive", type="cube", name=f"c{i}", location=[-1.5 + 1.5 * i, 0, 0], size=0.6, colour=c)


CASES = [
    # (name, task, scene builder, check that must fail)
    ("bounces twice, asked three times", "m01", lambda w: bounce(w, 2), "bounces"),
    ("bounces three times (control)", "m01", lambda w: bounce(w, 3), None),
    ("blue cube at the end of the row", "s01", lambda w: row(w, ["blue", "white", "white"]), "middle_of_row"),
    ("ball floating above the table", "s02", lambda w: table_and_ball(w, [0, 0, 1.1]), "on_surface"),
    ("ball out of view", "m01", lambda w: (bounce(w, 3), w.call("set_camera", look_at=[8, 1.2])), "in_view"),
    ("ball hidden behind a wall", "m01", lambda w: (bounce(w, 3), w.call(
        "add_primitive", type="cube", name="wall", location=[0, 0], size=3, layer="front")), "not_hidden"),
    ("half a turn instead of one", "m02", lambda w: (
        w.call("add_primitive", type="cube", name="cube", location=[0, 0]),
        w.call("keyframe", name="cube", property="rotation", frame=1, value=0),
        w.call("keyframe", name="cube", property="rotation", frame=48, value=180)), "spins"),
    ("ball goes through the table", "s02", lambda w: (
        table_and_ball(w, {"on_top_of": "table"}),
        w.call("keyframe", name="ball", property="location", frame=1, value=[-1.5, 0.6]),
        w.call("keyframe", name="ball", property="location", frame=40, value=[1.5, 0.6])), "no_collision"),
    ("ball hangs in the air past the table edge", "m03", lambda w: (
        w.call("add_asset", asset="table", name="table", location=[0, 0]),
        w.call("add_primitive", type="sphere", name="ball", location={"on_top_of": "table"}, size=0.18,
               colour="yellow"),
        w.call("keyframe", name="ball", property="location", frame=1, value={"on_top_of": "table"}),
        w.call("keyframe", name="ball", property="location", frame=30, value=[1.2, 0.75]),
        w.call("keyframe", name="ball", property="location", frame=50, value=[1.2, 0.75]),
        w.call("keyframe", name="ball", property="location", frame=60, value=[1.4, 0])), "no_hover"),
    ("pan that doesn't move", "m05", lambda w: (
        table_and_ball(w, {"on_top_of": "table"}),
        w.call("add_asset", asset="tree", name="tree", location=[-3, 0], layer="back"),
        w.call("camera_move", kind="pan", target="table", start_frame=1, end_frame=40)), "camera_move"),
    ("figure walks the wrong way", "f01", lambda w: (
        w.call("add_stick_figure", name="man", location=[1, 0]),
        w.call("play_action", name="man", action="walk", seconds=4, direction="left"),
        w.call("set_camera", look_at=[-1, 1.5], width=9)), "moves"),
    ("figure walks right for 4 s (control)", "f01", lambda w: (
        w.call("add_stick_figure", name="man", location=[-3, 0]),
        w.call("play_action", name="man", action="walk", seconds=4, direction="right"),
        w.call("set_camera", look_at=[-0.2, 1.5], width=9)), None),
    ("waves, then walks (wrong order)", "q01", lambda w: (
        w.call("add_stick_figure", name="man", location=[-2.5, 0]),
        w.call("play_action", name="man", action="wave"),
        w.call("play_action", name="man", action="walk", to=0)), "actions_in_order"),
    ("figure walks through the table", "p01", lambda w: (
        w.call("add_asset", asset="table", name="table", location=[0.5, 0]),
        w.call("add_stick_figure", name="man", location=[-2.5, 0]),
        w.call("play_action", name="man", action="walk", to=3.0),
        w.call("play_action", name="man", action="wave"),
        w.call("set_camera", look_at=[0.3, 1.5], width=9)), "no_collision"),
    ("figure stops far from the table", "p01", lambda w: (
        w.call("add_asset", asset="table", name="table", location=[2.5, 0]),
        w.call("add_stick_figure", name="man", location=[-3, 0]),
        w.call("play_action", name="man", action="walk", to=-0.5),
        w.call("play_action", name="man", action="wave"),
        w.call("set_camera", look_at=[0, 1.5], width=9)), "reaches"),
]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    failures = []
    with BlenderWorker(config.OUTPUTS / "test_checker") as w:
        for name, tid, build, must_fail in CASES:
            w.call("scene_reset")
            build(w)
            rep = check_task(TASKS[tid], w.call("sample_scene"), DEFAULTS)
            failed = sorted({r["check"] for r in rep["results"] if not r["ok"]})
            if must_fail is None:
                good = rep["passed"]
            else:
                good = must_fail in failed
            print(f"{'ok ' if good else 'BAD'} {name}: failed checks {failed}")
            for r in rep["results"]:
                if not r["ok"]:
                    print("      ", r["check"], "->", r["detail"])
            if not good:
                failures.append(name)
    assert not failures, failures
    print("all checker tests passed")


if __name__ == "__main__":
    main()
