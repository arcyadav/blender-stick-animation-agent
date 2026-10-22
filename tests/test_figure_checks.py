"""Figure checks catch broken motion; the library's own motion passes.  python -m tests.test_figure_checks

Runs without Blender: the joint tracks come straight from blender_worker/motion.py.
"""
import copy
import sys

from blender_worker import motion as M
from checks import figure_checks as FC
from checks.checker import Scene


def sample(fig, fps=24):
    frames = sorted(fig.frames(fig.end))
    track = fig.frames(fig.end)
    joints = {j: [list(track[f][j]) for f in frames] for j in M.JOINTS}
    return {"frames": frames, "fps": fps, "objects": {fig.name: {"kind": "figure", "frames": []}},
            "camera": [], "collisions": [],
            "figures": {fig.name: {"segments": fig.segments, "radius": fig.r, "leg": fig.L, "joints": joints}}}


def run(s, fn, **args):
    S = Scene(s)
    name = next(iter(s["figures"]))
    return fn(S, {"role": name, **args}, {name: name})


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    fig = M.Figure("man", -3, 0, facing="right")
    fig.play("walk", to_x=1.0)
    fig.play("react")
    fig.play("walk_sad", direction="left", seconds=2, speed=0.7)
    fig.play("wave")
    good = sample(fig)
    bad = []

    for name, fn in (("grounded", FC.c_grounded), ("no_foot_slide", FC.c_no_foot_slide), ("no_pops", FC.c_no_pops)):
        ok, detail = run(good, fn)
        print("ok " if ok else "BAD", "library motion passes", name, "->", detail)
        if not ok:
            bad.append(name)

    # moonwalk: the whole figure drifts 1.5 cm per frame, so planted feet slide
    s = copy.deepcopy(good)
    for j, tr in s["figures"]["man"]["joints"].items():
        for i, p in enumerate(tr):
            p[0] += 0.015 * i
    ok, detail = run(s, FC.c_no_foot_slide)
    print("ok " if not ok else "BAD", "moonwalk fails no_foot_slide ->", detail)
    bad += [] if not ok else ["moonwalk"]

    # a pop: one frame where the arm teleports
    s = copy.deepcopy(good)
    i = 40
    for j in ("l_elbow", "l_wrist"):
        s["figures"]["man"]["joints"][j][i][2] += 0.3
    ok, detail = run(s, FC.c_no_pops)
    print("ok " if not ok else "BAD", "teleporting arm fails no_pops ->", detail)
    bad += [] if not ok else ["pop"]

    # floating 5 cm above the ground
    s = copy.deepcopy(good)
    for tr in s["figures"]["man"]["joints"].values():
        for p in tr:
            p[2] += 0.05
    ok, detail = run(s, FC.c_grounded)
    print("ok " if not ok else "BAD", "floating figure fails grounded ->", detail)
    bad += [] if not ok else ["float"]

    ok, detail = run(good, FC.c_actions_in_order, actions=["walk", "react", "walk", "wave"])
    print("ok " if ok else "BAD", "actions in order ->", detail)
    bad += [] if ok else ["order"]
    ok, detail = run(good, FC.c_actions_in_order, actions=["wave", "walk"])
    print("ok " if not ok else "BAD", "wrong order fails ->", detail)
    bad += [] if not ok else ["order2"]

    assert not bad, bad
    print("all figure check tests passed")


if __name__ == "__main__":
    main()
