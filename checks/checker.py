"""Checks a finished scene against a task from tasks.json.

Input is the per-frame data from the worker's `sample_scene` tool, so this runs in plain Python.
Every check returns (ok, detail); details are written for the agent ("touches the ground 2 times,
expected 3") because the report is what the fix loop sends back.
"""
import itertools
import math
import re

from checks import figure_checks

TOL = {"contact_m": 0.02, "rest_m": 0.01, "bounce_rise_m": 0.05, "next_to_gap_m": 0.5,
       "in_view_inside": 0.9, "in_view_most": 0.75, "visible": 0.4}

COLOUR_NAMES = {
    "red": (0.8, 0.05, 0.05), "orange": (0.9, 0.35, 0.02), "yellow": (0.95, 0.8, 0.05),
    "green": (0.1, 0.6, 0.12), "blue": (0.05, 0.2, 0.8), "purple": (0.45, 0.1, 0.7),
    "pink": (0.95, 0.4, 0.6), "white": (0.9, 0.9, 0.9), "black": (0.02, 0.02, 0.02),
    "grey": (0.4, 0.4, 0.4), "brown": (0.35, 0.18, 0.07),
}
GROUP_KEYS = {"count": "role", "row": "roles", "middle_of_row": "row"}


def colour_name(rgb):
    return min(COLOUR_NAMES, key=lambda k: sum((a - b) ** 2 for a, b in zip(COLOUR_NAMES[k], rgb)))


# ---------------------------------------------------------------- scene access

class Scene:
    def __init__(self, sample):
        self.s = sample
        self.n = len(sample["frames"])
        self.frames = sample["frames"]
        self.fps = sample["fps"]

    def names(self):
        return list(self.s["objects"])

    def kind(self, name):
        return self.s["objects"][name]["kind"]

    def f(self, name, i):
        return self.s["objects"][name]["frames"][i]

    def idx(self, which):
        return {"first": 0, "last": self.n - 1}.get(which, which)

    def bottom(self, name, i):
        e = self.f(name, i)
        return ((e["lo"][0] + e["hi"][0]) / 2, (e["lo"][1] + e["hi"][1]) / 2, e["lo"][2])

    def centre(self, name, i):
        e = self.f(name, i)
        return tuple((a + b) / 2 for a, b in zip(e["lo"], e["hi"]))

    def top(self, name, i):
        o = self.s["objects"][name]
        e = self.f(name, i)
        return e["lo"][2] + o["top_z"] * e["scale"][2] if o.get("top_z") else e["hi"][2]

    def colour(self, name, i=0):
        c = self.f(name, i)["colour"]
        return colour_name(c) if c else None

    def right(self, i=0):
        r = self.s["camera"][i]["right"]
        n = math.hypot(r[0], r[1]) or 1
        return (r[0] / n, r[1] / n)

    def toward_camera(self, i=0):
        f = self.s["camera"][i]["fwd"]
        n = math.hypot(f[0], f[1]) or 1
        return (-f[0] / n, -f[1] / n)

    def along(self, name, i, axis):
        c = self.centre(name, i)
        return c[0] * axis[0] + c[1] * axis[1]

    def moved(self, name):
        a, b = self.f(name, 0), self.f(name, self.n - 1)
        return any(abs(x - y) > 0.01 for x, y in zip(a["lo"] + a["hi"], b["lo"] + b["hi"])) or any(
            abs(self.f(name, i)["lo"][2] - a["lo"][2]) > 0.01 for i in range(0, self.n, 3))

    def support_under(self, name, i):
        """Name of what `name` rests on at frame i ('ground', another object) or None."""
        x, y, z = self.bottom(name, i)
        if abs(z) <= TOL["rest_m"]:
            return "ground"
        for other in self.names():
            if other == name:
                continue
            e = self.f(other, i)
            if (e["lo"][0] - 0.01 <= x <= e["hi"][0] + 0.01 and e["lo"][1] - 0.01 <= y <= e["hi"][1] + 0.01
                    and abs(self.top(other, i) - z) <= TOL["contact_m"]):
                return other
        return None


# ---------------------------------------------------------------- role binding

def _group_roles(task):
    groups = set()
    for c in task["checks"]:
        k, v = next(iter(c.items()))
        if k in GROUP_KEYS and isinstance(v, dict) and isinstance(v.get(GROUP_KEYS[k]), str):
            groups.add(v[GROUP_KEYS[k]])
        if isinstance(v, dict):
            for ref in (v.get("target"), v.get("role")):
                if isinstance(ref, str) and "." in ref:
                    groups.add(ref.split(".")[0])
    return groups


def _matches(scene, name, spec):
    if scene.kind(name) != spec["kind"]:
        return False
    return "colour" not in spec or scene.colour(name, 0) == spec["colour"]


def bindings(task, scene):
    """All ways to assign scene objects to the task's roles (groups get every match)."""
    roles = task.get("roles", {})
    groups = _group_roles(task)
    fixed = {r: [n for n in scene.names() if _matches(scene, n, roles[r])] for r in groups if r in roles}
    singles = [r for r in roles if r not in groups]
    options = [[n for n in scene.names() if _matches(scene, n, roles[r])] or [None] for r in singles]
    out = []
    for combo in itertools.product(*options):
        used = [c for c in combo if c]
        if len(used) != len(set(used)):
            continue
        out.append({**fixed, **dict(zip(singles, combo))})
        if len(out) >= 200:
            break
    return out or [{**fixed, **{r: None for r in singles}}]


# ---------------------------------------------------------------- checks

class Missing(Exception):
    pass


def _one(b, role):
    if role in ("camera", "ground"):
        return role
    base, _, pick = role.partition(".")
    v = b.get(base)
    if v is None or v == []:
        raise Missing(f"nothing in the scene matches '{base}'")
    if isinstance(v, list):
        if not pick:
            return v[0]
        return v  # resolved by the caller with the camera axis
    return v


def _pick(scene, b, role):
    v = _one(b, role)
    if isinstance(v, list):
        axis = scene.right(0)
        ordered = sorted(v, key=lambda n: scene.along(n, 0, axis))
        return ordered[0] if role.endswith(".left") else ordered[-1]
    return v


def _many(b, roles):
    out = []
    for r in ([roles] if isinstance(roles, str) else roles):
        v = b.get(r)
        if v is None or v == []:
            raise Missing(f"nothing in the scene matches '{r}'")
        out.extend(v if isinstance(v, list) else [v])
    return out


def c_count(S, a, b):
    got = len(b.get(a["role"]) or [])
    return got == a["n"], f"{got} object(s) match '{a['role']}', expected {a['n']}"


def _frame_set(S, frames):
    if frames in (None, "all"):
        return list(range(S.n))
    if frames == "most":
        return "most"
    if frames == "key":
        return [i for i in range(S.n) if "visible" in S.f(S.names()[0], i)] if S.names() else []
    if frames in ("first", "last"):
        return [S.idx(frames)]
    return [S.frames.index(f) for f in frames]


def _inside(scr):
    x0, y0, x1, y1 = scr
    if x1 - x0 < 1e-4 or y1 - y0 < 1e-4:          # scaled to nothing: judge by its position
        return float(0 <= x0 <= 1 and 0 <= y0 <= 1)
    w, h = x1 - x0, y1 - y0
    ix = max(0.0, min(x1, 1) - max(x0, 0))
    iy = max(0.0, min(y1, 1) - max(y0, 0))
    return (ix * iy) / (w * h)


def c_in_view(S, a, b, frames=None, region=None):
    names = _many(b, a)
    sel = _frame_set(S, frames)
    bad = []
    for n in names:
        idxs = range(S.n) if sel == "most" else sel
        ok_frames = [i for i in idxs
                     if S.f(n, i)["in_front"] and _inside(S.f(n, i)["screen"]) >= TOL["in_view_inside"]
                     and (region != "middle_third" or 1 / 3 <= (S.f(n, i)["screen"][0] + S.f(n, i)["screen"][2]) / 2 <= 2 / 3)]
        need = math.ceil(TOL["in_view_most"] * S.n) if sel == "most" else len(list(idxs))
        if len(ok_frames) < need:
            out = [S.frames[i] for i in idxs if i not in ok_frames]
            where = " in the middle third" if region else ""
            bad.append(f"{n} not fully in view{where} on {len(out)} frame(s) (e.g. frame {out[0]})")
    return not bad, "; ".join(bad) or "in view"


def c_not_hidden(S, a, b, frames=None):
    bad = []
    for n in _many(b, a):
        hidden = [S.frames[i] for i in range(S.n)
                  if S.f(n, i).get("visible") is not None and S.f(n, i)["visible"] < TOL["visible"]]
        if hidden:
            bad.append(f"{n} is hidden behind something at frame(s) {hidden[:4]}")
    return not bad, "; ".join(bad) or "visible"


def c_on_surface(S, a, b):
    role, surface = a["role"], a.get("surface")
    i = S.idx(a.get("frame", "last"))
    n = _one(b, role)
    under = S.support_under(n, i)
    if surface is None:
        return under is not None, f"{n} rests on {under}" if under else \
            f"{n} is floating or sunk (bottom at {S.bottom(n, i)[2]:.2f} m, frame {S.frames[i]})"
    want = surface if surface == "ground" else _one(b, surface)
    return under == want, f"{n} rests on {under or 'nothing'} at frame {S.frames[i]}, expected {want}"


def c_static_on_surface(S, b):
    bad = []
    for n in {x for v in b.values() if v for x in (v if isinstance(v, list) else [v])}:
        if not S.moved(n) and S.support_under(n, 0) is None:
            bad.append(f"{n} is floating or sunk (bottom at {S.bottom(n, 0)[2]:.2f} m)")
    return not bad, "; ".join(bad) or "everything rests on something"


def _row(S, names):
    axis = S.right(0)
    return sorted(names, key=lambda n: S.along(n, S.n - 1, axis))


def c_row(S, a, b):
    names = _row(S, _many(b, a["roles"]))
    if len(names) < 3:
        return len(names) == 2, f"{len(names)} object(s) in the row"
    pts = [S.centre(n, S.n - 1)[:2] for n in names]
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    L = math.hypot(x1 - x0, y1 - y0) or 1e-6
    dev = max(abs((x1 - x0) * (y0 - p[1]) - (x0 - p[0]) * (y1 - y0)) / L for p in pts)
    gaps = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    mean = sum(gaps) / len(gaps)
    even = all(abs(g - mean) <= 0.25 * mean for g in gaps)
    ok = dev <= 0.25 * mean and even
    return ok, f"row {names}: off the line by {dev:.2f} m, gaps {[round(g, 2) for g in gaps]}"


def c_middle_of_row(S, a, b):
    names = _row(S, _many(b, a["row"]))
    m = _one(b, a["role"])
    mid = names[len(names) // 2] if len(names) % 2 else None
    return m == mid, f"middle of the row is {mid}, '{a['role']}' is {m}"


def c_relation(S, a, b):
    A, B = _one(b, a["a"]), _one(b, a["b"])
    i = S.n - 1
    rel = a["rel"]
    if rel in ("left_of", "right_of"):
        axis = S.right(i)
        d = S.along(A, i, axis) - S.along(B, i, axis)
        ok = d < -0.05 if rel == "left_of" else d > 0.05
        return ok, f"{A} is {abs(d):.2f} m to the {'left' if d < 0 else 'right'} of {B} (as seen by the camera)"
    if rel in ("in_front_of", "behind"):
        axis = S.toward_camera(i)
        d = S.along(A, i, axis) - S.along(B, i, axis)
        ok = d > 0.05 if rel == "in_front_of" else d < -0.05
        return ok, f"{A} is {abs(d):.2f} m {'in front of' if d > 0 else 'behind'} {B}"
    if rel == "on_top_of":
        under = S.support_under(A, i)
        return under == B, f"{A} rests on {under or 'nothing'}, expected {B}"
    if rel == "next_to":
        ea, eb = S.f(A, i), S.f(B, i)
        gap = max(eb["lo"][0] - ea["hi"][0], ea["lo"][0] - eb["hi"][0], 0)     # 2D: across the screen
        return gap <= TOL["next_to_gap_m"], f"gap between {A} and {B} is {gap:.2f} m (max {TOL['next_to_gap_m']})"
    raise ValueError(rel)


def _heights_over(S, n, surface, b):
    out = []
    for i in range(S.n):
        base = 0.0 if surface == "ground" else S.top(_one(b, surface), i)
        out.append(S.bottom(n, i)[2] - base)
    return out


def c_bounces(S, a, b):
    n = _one(b, a["role"])
    h = _heights_over(S, n, a.get("surface", "ground"), b)
    # a bounce = arriving at the surface from the air, then rising clearly off it again
    arrivals = [i for i in range(1, S.n) if h[i] <= TOL["contact_m"] < h[i - 1]]
    bounces = [S.frames[i] for i in arrivals if max(h[i + 1:], default=0) >= TOL["bounce_rise_m"]]
    ok = len(bounces) == a["n"]
    return ok, f"{n} bounces {len(bounces)} time(s) (frames {bounces}), expected {a['n']}"


def c_spins(S, a, b):
    n = _one(b, a["role"])
    ax = "xyz".index(a.get("axis", "y"))
    rots = [S.f(n, i)["rot"][ax] for i in range(S.n)]
    total = sum(abs(rots[i + 1] - rots[i]) for i in range(S.n - 1))
    turns = total / 360
    moving = [i for i in range(S.n - 1) if abs(rots[i + 1] - rots[i]) > 0.01]
    secs = (moving[-1] - moving[0] + 1) / S.fps if moving else 0
    ok = abs(turns - a["turns"]) <= 0.1 * a["turns"] and (
        "seconds" not in a or abs(secs - a["seconds"]) <= 0.2 * a["seconds"])
    return ok, f"{n} turns {turns:.2f} time(s) in {secs:.2f} s, " \
               f"expected {a['turns']} in {a.get('seconds', 'any')} s"


DIRS = {"right": lambda S: S.right(0), "left": lambda S: tuple(-x for x in S.right(0)),
        "toward": lambda S: S.toward_camera(0), "away": lambda S: tuple(-x for x in S.toward_camera(0))}


def c_moves(S, a, b):
    n = _one(b, a["role"])
    axis = DIRS[a["direction"]](S)
    p0, p1 = S.bottom(n, 0), S.bottom(n, S.n - 1)
    d = (p1[0] - p0[0]) * axis[0] + (p1[1] - p0[1]) * axis[1]
    return d >= a["min_m"], f"{n} moves {d:.2f} m {a['direction']} (as seen by the camera), at least {a['min_m']} m needed"


def c_scale_change(S, a, b):
    n = _one(b, a["role"])
    s0 = sum(S.f(n, 0)["scale"]) / 3
    s1 = sum(S.f(n, S.n - 1)["scale"]) / 3

    def near(x, want):
        return x <= 0.05 if want == 0 else abs(x - want) <= 0.1 * want
    ok = near(s0, a["from"]) and near(s1, a["to"])
    return ok, f"{n} scale goes {s0:.2f} → {s1:.2f}, expected {a['from']} → {a['to']}"


def c_colour_change(S, a, b):
    n = _one(b, a["role"])
    c0, c1 = S.colour(n, 0), S.colour(n, S.n - 1)
    ok = c0 == a["from"] and c1 == a["to"]
    return ok, f"{n} colour goes {c0} → {c1}, expected {a['from']} → {a['to']}"


def c_light(S, a, b):
    return S.s["light"] == a["preset"], f"light is {S.s['light']}, expected {a['preset']}"


def c_camera_move(S, a, b):
    """2D camera: it slides (pan, follow) and zooms (the visible width changes); it can't orbit."""
    kind = {"dolly_in": "zoom_in", "dolly_out": "zoom_out"}.get(a["kind"], a["kind"])
    cams = S.s["camera"]
    if kind == "orbit":
        return False, "the world is 2D, so the camera can't orbit"
    t = _pick(S, b, a["target"]) if a.get("target") else None
    w0, w1 = cams[0].get("width", 0), cams[-1].get("width", 0)
    travel = abs(cams[-1]["loc"][0] - cams[0]["loc"][0])
    if kind in ("zoom_in", "zoom_out"):
        ok = w1 <= 0.8 * w0 if kind == "zoom_in" else w1 >= 1.2 * w0
        return ok, f"visible width goes {w0:.1f} → {w1:.1f} m ({'≤ 80%' if kind == 'zoom_in' else '≥ 120%'} needed)"
    if kind == "follow":
        centred = sum(1 / 3 <= (S.f(t, i)["screen"][0] + S.f(t, i)["screen"][2]) / 2 <= 2 / 3 for i in range(S.n))
        ok = centred >= 0.9 * S.n and travel >= 1.0
        return ok, f"{t} in the middle third on {centred}/{S.n} frames, camera travels {travel:.1f} m"
    if kind == "pan":
        ok = travel >= 1.0 and abs(w1 - w0) <= 0.1 * w0
        where = ""
        if t:
            c = (S.f(t, S.n - 1)["screen"][0] + S.f(t, S.n - 1)["screen"][2]) / 2
            ok = ok and 0.25 <= c <= 0.75
            where = f", {t} ends at {c:.0%} across the frame"
        return ok, f"camera slides {travel:.1f} m sideways (≥ 1 m needed), width {w0:.1f} → {w1:.1f} m{where}"
    raise ValueError(kind)


def c_no_hover(S, a, b):
    """Nothing hangs in the air: an unsupported object must be moving up or down (a fall, a bounce),
    not drifting sideways at a constant height for more than a quarter of a second."""
    names = [n for n in _all_roles(b) if S.kind(n) != "figure"]
    bad = []
    limit = max(3, round(0.25 * S.fps))
    for n in names:
        run = 0
        held = _held_frames(S, n)
        for i in range(1, S.n):
            if S.frames[i] in held:              # in someone's hand: carried, not hanging
                run = 0
                continue
            dz = abs(S.f(n, i)["lo"][2] - S.f(n, i - 1)["lo"][2])
            floating = S.support_under(n, i) is None and dz < 0.002
            run = run + 1 if floating else 0
            if run > limit:
                z = S.bottom(n, i)[2]
                bad.append(f"{n} hangs in the air at {z:.2f} m with nothing under it (frames "
                           f"{S.frames[i - run + 1]}–{S.frames[i]})")
                break
    return not bad, "; ".join(bad) or "nothing hangs in the air"


def _carried(S):
    """{(figure, object): frames the object is in that figure's hand, with a margin for the grab}."""
    out = {}
    for fig, F in S.s.get("figures", {}).items():
        for h in F.get("holds", []) + [g for g in F.get("sits", []) if g.get("obj")]:
            end = h["to"] if h["to"] is not None else S.frames[-1]
            out.setdefault((fig, h["obj"]), set()).update(range(h["from"] - 24, end + 25))
    return out


def _held_frames(S, name):
    frames = set()
    for (fig, obj), fs in _carried(S).items():
        if obj == name:
            frames |= fs
    return frames


def c_no_collision(S, a, b):
    names = set(_many(b, a)) if isinstance(a, list) else {
        x for v in b.values() if v for x in (v if isinstance(v, list) else [v])}
    carried = _carried(S)
    hits = [c for c in S.s["collisions"] if c[0] in names and c[1] in names
            and c[2] not in carried.get((c[0], c[1]), carried.get((c[1], c[0]), set()))]
    if not hits:
        return True, "no collisions"
    pairs = sorted({(c[0], c[1]) for c in hits})
    return False, "; ".join(f"{x} passes through {y} (from frame "
                            f"{min(c[2] for c in hits if (c[0], c[1]) == (x, y))})" for x, y in pairs)


def c_clip_length_s(S, a, b):
    secs = S.n / S.fps
    return a["min"] <= secs <= a["max"], f"clip is {secs:.1f} s (allowed {a['min']}–{a['max']} s)"


def c_distance_end(S, a, b):
    A, B = _one(b, a["a"]), _one(b, a["b"])
    pa, pb = S.bottom(A, S.n - 1), S.bottom(B, S.n - 1)
    d = abs(pa[0] - pb[0])
    return a.get("min_m", 0) <= d <= a["max_m"], f"{A} and {B} end {d:.2f} m apart " \
                                                 f"(allowed {a.get('min_m', 0)}–{a['max_m']} m)"


CHECKS = {
    "count": c_count, "in_view": None, "not_hidden": None, "on_surface": c_on_surface, "row": c_row,
    "middle_of_row": c_middle_of_row, "relation": c_relation, "bounces": c_bounces, "spins": c_spins,
    "moves": c_moves, "scale_change": c_scale_change, "colour_change": c_colour_change, "light": c_light,
    "camera_move": c_camera_move, "no_collision": c_no_collision, "clip_length_s": c_clip_length_s,
    "distance_end": c_distance_end, "no_hover": c_no_hover, **figure_checks.CHECKS,
}


def _run_one(S, check, b):
    key = next(k for k in check if k not in ("frames", "region"))
    arg = check[key]
    try:
        if arg == "all_roles" and key in ("in_view", "not_hidden"):
            # object names stand for themselves
            names = _all_roles(b)
            arg, b = names, {n: n for n in names}
        if key == "in_view":
            return key, *c_in_view(S, arg, b, check.get("frames"), check.get("region"))
        if key == "not_hidden":
            return key, *c_not_hidden(S, arg, b)
        if key == "on_surface" and arg == "all_static_roles":
            return key, *c_static_on_surface(S, b)
        if key == "no_collision" and arg == "all_roles":
            return key, *c_no_collision(S, None, b)
        if key == "no_hover":
            return key, *c_no_hover(S, arg, b)
        if arg == "all_figures":
            figs = [n for n in _all_roles(b) if S.kind(n) == "figure"]
            if not figs:
                return key, True, "no figures"
            if key not in figure_checks.CHECKS:
                return key, False, f"check '{key}' is not implemented yet"
            res = [CHECKS[key](S, {**{k: v for k, v in check.items() if k != key}, "role": f}, {**b, f: f})
                   for f in figs]
            return key, all(r[0] for r in res), "; ".join(r[1] for r in res)
        fn = CHECKS.get(key)
        if fn is None:
            return key, False, f"check '{key}' is not implemented yet"
        return key, *fn(S, arg, b)
    except Missing as e:
        return key, False, str(e)


def _all_roles(b):
    return sorted({x for v in b.values() if v for x in (v if isinstance(v, list) else [v])})


def check_task(task, sample, defaults=None):
    """→ {"passed": bool, "results": [{"check", "ok", "detail", "default"}], "binding": {...}}"""
    S = Scene(sample)
    skip = set(task.get("skip_defaults", []))
    checks = [(c, False) for c in task["checks"]] + [
        (c, True) for c in (defaults or []) if next(iter(c)) not in skip]
    best = None
    for b in bindings(task, S):
        results = []
        for c, is_default in checks:
            key, ok, detail = _run_one(S, c, b)
            results.append({"check": key, "ok": bool(ok), "detail": detail, "default": is_default})
        score = sum(r["ok"] for r in results)
        if best is None or score > best[0]:
            best = (score, results, b)
    _, results, b = best
    for r in results:                       # say how to make what's missing, so the agent can act on it
        m = re.match(r"nothing in the scene matches '(\w+)'", r["detail"])
        if m and m.group(1) in task.get("roles", {}):
            r["detail"] += f": the request needs {_how_to_make(task['roles'][m.group(1)])}"
    return {"passed": all(r["ok"] for r in results), "results": results, "binding": b}


ASSET_KINDS = {"table", "chair", "bench", "box", "lamp", "tree"}


def _how_to_make(spec):
    kind, colour = spec["kind"], spec.get("colour")
    c = f", colour='{colour}'" if colour else ""
    if kind == "figure":
        return f"a stick figure (add_stick_figure{'(colour=' + repr(colour) + ')' if colour else ''})"
    if kind in ASSET_KINDS:
        return f"a {colour + ' ' if colour else ''}{kind} (add_asset(asset='{kind}'{c}))"
    return f"a {colour + ' ' if colour else ''}{kind} (add_primitive(type='{kind}'{c}))"


def report_text(report):
    """Short text for the agent: failures first."""
    fails = [r for r in report["results"] if not r["ok"]]
    if not fails:
        return f"All {len(report['results'])} checks pass."
    lines = [f"{len(fails)} of {len(report['results'])} checks fail:"]
    lines += [f"- {r['check']}: {r['detail']}" for r in fails]
    return "\n".join(lines)
