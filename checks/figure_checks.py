"""Checks on stick figures, from the joint tracks and action timeline in `sample_scene`.

Each check is fn(S, args, binding) → (ok, detail), like the scene checks in checker.py.
"""
import math

WALKS = {"walk", "walk_happy", "walk_sad", "walk_worried"}
TOL = {"ground_m": 0.015, "planted_m": 0.004, "pop_min_m": 0.05, "faces_deg": 30}


def _fig(S, b, role):
    from checks.checker import Missing, _one
    n = _one(b, role)
    if n not in S.s.get("figures", {}):
        raise Missing(f"'{n}' is not a stick figure")
    return n, S.s["figures"][n]


def _matches(want, got):
    """'walk' matches any walk; a mood walk (walk_sad, …) only matches itself."""
    return got == want or (want == "walk" and got in WALKS)


def _segments(F, S):
    """Segments clipped to the clip's frame range."""
    out = []
    for g in F["segments"]:
        s, e = max(g["start"], S.frames[0]), min(g["end"], S.frames[-1])
        if s <= e:
            out.append({**g, "start": s, "end": e})
    return out


def _blend_frames(F):
    out = set()
    for g in F["segments"]:
        for key in ("blend",):                   # transitions: the feet may step into place
            if g.get(key):
                out.update(range(g[key][0] - 1, g[key][1] + 1))
    return out


def _lowest(F, i):
    J = F["joints"]
    return min(J[j][i][2] for j in ("l_toe", "r_toe", "l_ankle", "r_ankle")) - F["radius"]


def _pelvis_x(F, i):
    return F["joints"]["pelvis"][i][0]


def _facing_at(F, frame):
    cur = None
    for g in F["segments"]:
        if g["start"] <= frame:
            cur = g["facing"]
    return cur


# ---------------------------------------------------------------- quality (defaults)

def c_grounded(S, a, b):
    n, F = _fig(S, b, a["role"])
    low = [_lowest(F, i) for i in range(S.n)]
    worst = max(range(S.n), key=lambda i: abs(low[i]))
    ok = abs(low[worst]) <= TOL["ground_m"]
    state = "below" if low[worst] < 0 else "above"
    return ok, f"{n}'s lowest foot is {abs(low[worst]) * 100:.1f} cm {state} the ground at worst " \
               f"(frame {S.frames[worst]}, allowed {TOL['ground_m'] * 100:.1f} cm)"


def c_no_foot_slide(S, a, b):
    n, F = _fig(S, b, a["role"])
    limit = a.get("max_cm_per_frame", 0.5) / 100
    skip = _blend_frames(F)
    worst, where = 0.0, None
    for s in "lr":
        toe = F["joints"][f"{s}_toe"]
        for i in range(S.n - 1):
            if S.frames[i] in skip or S.frames[i + 1] in skip:
                continue
            down = toe[i][2] - F["radius"] <= TOL["planted_m"] and toe[i + 1][2] - F["radius"] <= TOL["planted_m"]
            if down:
                d = abs(toe[i + 1][0] - toe[i][0])
                if d > worst:
                    worst, where = d, (S.frames[i], s)
    ok = worst <= limit
    detail = f"{n}'s planted feet slide at most {worst * 100:.2f} cm per frame (allowed {limit * 100:.1f})"
    if where and not ok:
        detail += f", worst at frame {where[0]} ({'left' if where[1] == 'l' else 'right'} foot)"
    return ok, detail


def c_no_pops(S, a, b):
    """No joint jumps. A pop (a joint that teleports for a frame, or jumps and stays) is a sudden
    change of velocity: the acceleration on that frame is far above the acceleration two frames
    either side. A fast but eased move, like a flinch, speeds up and slows down over several frames."""
    n, F = _fig(S, b, a["role"])
    ratio = a.get("max_speed_ratio", 3.0)
    worst = (0.0, None, None)
    for j, track in F["joints"].items():
        acc = [0.0] + [math.dist([track[i + 1][k] - 2 * track[i][k] + track[i - 1][k] for k in range(3)], [0, 0, 0])
                       for i in range(1, S.n - 1)] + [0.0]
        for i, x in enumerate(acc):
            if x <= TOL["pop_min_m"]:
                continue
            around = max(acc[i - 2] if i >= 2 else 0.0, acc[i + 2] if i + 2 < len(acc) else 0.0, 0.01)
            if x / around > worst[0]:
                worst = (x / around, i, (j, x))
    r, i, jx = worst
    if i is None or r <= ratio:
        return True, f"{n} moves smoothly (no sudden jumps)"
    j, x = jx
    return False, f"{n}'s {j.replace('_', ' ')} jumps at frame {S.frames[i]} (its speed changes by " \
                  f"{x * 100:.1f} cm/frame at once, ×{r:.1f} the frames around it; allowed ×{ratio})"


def c_staging(S, a, b):
    _fig(S, b, a["role"])
    return True, "2D: every action is drawn in the picture plane"


# ---------------------------------------------------------------- what the task asks for

def c_actions_in_order(S, a, b):
    n, F = _fig(S, b, a["role"])
    got = [g["action"] for g in _segments(F, S)]
    want = a["actions"]
    k = 0
    for g in got:
        if k < len(want) and _matches(want[k], g):
            k += 1
    return k == len(want), f"{n} does {got or 'nothing'}; expected {want} in this order"


def c_action_duration(S, a, b):
    n, F = _fig(S, b, a["role"])
    frames = sum(g["end"] - g["start"] + 1 for g in _segments(F, S) if _matches(a["action"], g["action"]))
    secs = frames / S.fps
    ok = a.get("min_s", 0) <= secs <= a.get("max_s", 1e9)
    return ok, f"{n} does {a['action']} for {secs:.1f} s (allowed {a.get('min_s', 0)}–{a.get('max_s', '∞')} s)"


def c_speed(S, a, b):
    n, F = _fig(S, b, a["role"])
    segs = [g for g in _segments(F, S) if _matches(a["action"], g["action"])]
    if not segs:
        return False, f"{n} never does {a['action']}"
    sp = sum(g["speed"] for g in segs) / len(segs)
    rel = a["relative"]
    ok = sp <= 0.85 if rel == "slow" else sp >= 1.2 if rel == "fast" else 0.85 < sp < 1.2
    return ok, f"{n} does {a['action']} at speed {sp:.2f} (slow ≤ 0.85, fast ≥ 1.2), expected {rel}"


def _x_gap(S, A, B, i):
    ea, eb = S.f(A, i), S.f(B, i)
    return max(eb["lo"][0] - ea["hi"][0], ea["lo"][0] - eb["hi"][0], 0.0)


def _faces_toward(S, F, A, B, i):
    facing = _facing_at(F, S.frames[i])
    if facing not in ("left", "right"):
        return False, facing
    dx = S.centre(B, i)[0] - S.centre(A, i)[0]
    return (dx > 0) == (facing == "right"), facing


def c_reaches(S, a, b):
    from checks.checker import _pick
    n, F = _fig(S, b, a["role"])
    t = _pick(S, b, a["target"])
    i = S.n - 1
    gap = _x_gap(S, n, t, i)
    ok = gap <= a["within_m"]
    detail = f"{n} ends {gap:.2f} m from {t} (within {a['within_m']} m needed)"
    if a.get("facing"):
        toward, facing = _faces_toward(S, F, n, t, i)
        ok = ok and toward
        detail += f", facing {facing}" + ("" if toward else f" (not toward {t})")
    return ok, detail


def c_faces(S, a, b):
    n, F = _fig(S, b, a["a"])
    i = S.n - 1
    if a["b"] == "camera":
        facing = _facing_at(F, S.frames[i])
        return facing == "front", f"{n} faces {facing} at the end (expected the camera, 'front')"
    from checks.checker import _pick
    t = _pick(S, b, a["b"])
    toward, facing = _faces_toward(S, F, n, t, i)
    return toward, f"{n} faces {facing} at the end; {t} is to the " \
                   f"{'right' if S.centre(t, i)[0] > S.centre(n, i)[0] else 'left'}"


def c_returns(S, a, b):
    n, F = _fig(S, b, a["role"])
    xs = [_pelvis_x(F, i) for i in range(S.n)]
    away = max(abs(x - xs[0]) for x in xs)
    back = abs(xs[-1] - xs[0])
    ok = away >= 1.0 and back <= a["within_m"]
    return ok, f"{n} goes {away:.2f} m away (≥ 1 m needed) and ends {back:.2f} m from its start " \
               f"(within {a['within_m']} m needed)"


def c_same_time(S, a, b):
    from checks.checker import _many
    names = _many(b, a["roles"])
    spans = []
    for n in names:
        F = S.s["figures"].get(n)
        segs = [g for g in _segments(F, S) if _matches(a["action"], g["action"])] if F else []
        if not segs:
            return False, f"{n} never does {a['action']}"
        spans.append((n, segs))
    best = 0
    for g in spans[0][1]:
        for h in spans[1][1]:
            best = max(best, min(g["end"], h["end"]) - max(g["start"], h["start"]) + 1)
    secs = best / S.fps
    return secs >= 0.5, f"{' and '.join(n for n, _ in spans)} do {a['action']} together for {max(secs, 0):.1f} s " \
                        f"(≥ 0.5 s needed)"


def c_start_near(S, a, b):
    from checks.checker import _pick
    n, F = _fig(S, b, a["role"])
    t = _pick(S, b, a["target"])
    gap = _x_gap(S, n, t, 0)
    return gap <= a["within_m"], f"{n} starts {gap:.2f} m from {t} (within {a['within_m']} m needed)"


def c_passes(S, a, b):
    from checks.checker import _pick
    n, F = _fig(S, b, a["role"])
    t = _pick(S, b, a["target"])
    d0 = S.centre(n, 0)[0] - S.centre(t, 0)[0]
    d1 = S.centre(n, S.n - 1)[0] - S.centre(t, S.n - 1)[0]
    ok = d0 * d1 < 0 and abs(d0) > 0.3 and abs(d1) > 0.3
    side = lambda d: "left" if d < 0 else "right"   # noqa: E731
    return ok, f"{n} starts to the {side(d0)} of {t} and ends to the {side(d1)}"


CHECKS = {
    "grounded": c_grounded, "no_foot_slide": c_no_foot_slide, "no_pops": c_no_pops, "staging": c_staging,
    "actions_in_order": c_actions_in_order, "action_duration": c_action_duration, "speed": c_speed,
    "reaches": c_reaches, "faces": c_faces, "returns": c_returns, "same_time": c_same_time,
    "start_near": c_start_near, "passes": c_passes,
}
