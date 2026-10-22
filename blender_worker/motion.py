"""Stick-figure motion in 2D (pure Python, no bpy, so it is testable outside Blender).

Poses are dicts joint → (u, v) in leg-length units (hip → ankle = 1), v up from the ground.
  side view : u = forward (the way the figure faces)
  front view: u = screen-right (the figure's own left), the figure faces the camera
Sources:
  walk, walk_happy, walk_sad, walk_worried : Project 3 joint tracks (side view, code keyframes)
  wave                                     : Project 3 rotations from my own video (front view)
  idle, look_down, react                   : keyed here, exaggerated for a stick figure
"""
import json
import math
import os

JOINTS = ["pelvis", "chest", "neck", "head_top", "l_hip", "r_hip", "l_knee", "r_knee", "l_ankle", "r_ankle",
          "l_toe", "r_toe", "l_shoulder", "r_shoulder", "l_elbow", "r_elbow", "l_wrist", "r_wrist"]
# lengths shared by every Project 3 track (leg units)
SPINE, NECK, HEAD, UPPER, FORE, THIGH, SHIN, FOOT = 0.55, 0.2, 0.35, 0.36, 0.34, 0.5, 0.5, 0.25
SHOULDER_AT = 0.352                  # shoulder height between chest and neck
ANKLE_V = 0.2                        # ankle height in the P3 tracks (toe tip at ~0.075)
STAND_V = 1.17                       # pelvis height standing (legs nearly straight)
FRONT_V = 1.19                       # facing the camera: legs straight, so the knees don't bow
HIP_W, SHOULDER_W = 0.1, 0.08        # front view half-widths
HEAD_TOP_V = STAND_V + SPINE + NECK + HEAD - 0.075   # standing height above the ground

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "motions")
WALKS = ["walk", "walk_happy", "walk_sad", "walk_worried"]
ACTIONS = WALKS + ["wave", "idle", "look_down", "react"]
VIEW = {**{w: "side" for w in WALKS}, "wave": "front", "idle": "front", "look_down": "side", "react": "side"}
FPS = 24


def _dir(deg):
    a = math.radians(deg)
    return math.cos(a), math.sin(a)


def _add(p, d, s=1.0):
    return p[0] + d[0] * s, p[1] + d[1] * s


def _lerp(a, b, t):
    return a + (b - a) * t


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def _leg_ik(hip, ankle, bend):
    """Knee for a two-bone leg; bend = +1 puts the knee toward +u."""
    dx, dy = ankle[0] - hip[0], ankle[1] - hip[1]
    d = math.hypot(dx, dy)
    reach = THIGH + SHIN
    if d >= reach * 0.9999:
        return _add(hip, (dx / d, dy / d), THIGH)
    a = (THIGH ** 2 - SHIN ** 2 + d * d) / (2 * d)
    h = math.sqrt(max(THIGH ** 2 - a * a, 0.0))
    mx, my = hip[0] + dx * a / d, hip[1] + dy * a / d
    px, py = -dy / d, dx / d                       # perpendicular
    if px * bend < 0:
        px, py = -px, -py
    return mx + px * h, my + py * h


# ---------------------------------------------------------------- pose builders

def side_pose(pelvis=(0.0, STAND_V), lean=0.0, head=0.0, arms=None, feet=None):
    """Standing profile. Angles in degrees: lean / head > 0 bend forward; arm angles are measured
    from hanging straight down, > 0 swings forward. feet = ankle u per side."""
    arms = arms or {"l": (-4, 6), "r": (4, 14)}
    feet = feet or {"l": 0.05, "r": -0.05}
    up = 90 - lean
    chest = _add(pelvis, _dir(up), SPINE)
    neck = _add(chest, _dir(up), NECK)
    p = {"pelvis": pelvis, "chest": chest, "neck": neck, "head_top": _add(neck, _dir(up - head), HEAD)}
    sh = (_lerp(chest[0], neck[0], SHOULDER_AT), _lerp(chest[1], neck[1], SHOULDER_AT))
    for s in "lr":
        up_a, fore_a = arms[s]
        p[f"{s}_shoulder"] = sh
        p[f"{s}_elbow"] = _add(sh, _dir(-90 + up_a), UPPER)
        p[f"{s}_wrist"] = _add(p[f"{s}_elbow"], _dir(-90 + fore_a), FORE)
        ankle = (feet[s], ANKLE_V)
        p[f"{s}_hip"] = pelvis
        p[f"{s}_ankle"] = ankle
        p[f"{s}_knee"] = _leg_ik(pelvis, ankle, +1)
        p[f"{s}_toe"] = _add(ankle, _dir(-30), FOOT)
    return p


def front_pose(pelvis=(0.0, FRONT_V), tilt=0.0, head=0.0, arms=None, stance=0.05):
    """Facing the camera; u = screen-right = the figure's left. Angles counter-clockwise on screen.
    arms = per side (upper, forearm) rotation from the resting pose (hanging, slightly out)."""
    arms = arms or {}
    up = 90 + tilt
    chest = _add(pelvis, _dir(up), SPINE)
    neck = _add(chest, _dir(up), NECK)
    p = {"pelvis": pelvis, "chest": chest, "neck": neck, "head_top": _add(neck, _dir(up + head), HEAD)}
    mid = (_lerp(chest[0], neck[0], SHOULDER_AT), _lerp(chest[1], neck[1], SHOULDER_AT))
    for s, side in (("l", 1), ("r", -1)):
        du, df = arms.get(s, (0.0, 0.0))
        rest_up, rest_fore = -90 + 18 * side, -90 + 12 * side
        sh = _add(mid, _dir(tilt if side > 0 else 180 + tilt), SHOULDER_W)
        p[f"{s}_shoulder"] = sh
        p[f"{s}_elbow"] = _add(sh, _dir(rest_up + du), UPPER)
        p[f"{s}_wrist"] = _add(p[f"{s}_elbow"], _dir(rest_fore + df), FORE)
        hip = (pelvis[0] + side * HIP_W, pelvis[1])
        ankle = (side * (HIP_W + stance), ANKLE_V)
        p[f"{s}_hip"] = hip
        p[f"{s}_ankle"] = ankle
        p[f"{s}_knee"] = _leg_ik(hip, ankle, side)
        p[f"{s}_toe"] = (ankle[0] + side * 0.12, ankle[1] - 0.125)
    return p


def rest_pose(view):
    return front_pose() if view == "front" else side_pose()


def lerp_pose(a, b, t):
    return {j: (_lerp(a[j][0], b[j][0], t), _lerp(a[j][1], b[j][1], t)) for j in JOINTS}


# ---------------------------------------------------------------- clips

class Clip:
    """A library action: a list of poses at `fps`. Walks also carry stride (u per cycle), and the
    frames of half a cycle (a step ending on a contact pose, both feet down)."""

    def __init__(self, name, poses, fps, loop, view, stride=0.0):
        self.name, self.poses, self.fps, self.loop, self.view, self.stride = name, poses, fps, loop, view, stride
        self.n = len(poses)
        self.half = self.n / 2 if stride else None

    def at(self, t):
        """Pose at clip frame t (float). Loops repeat (walks move on by a stride per cycle);
        one-shot clips hold their last pose."""
        if not self.loop:
            t = min(max(t, 0.0), self.n - 1)
            i = min(int(t), self.n - 2) if self.n > 1 else 0
            return lerp_pose(self.poses[i], self.poses[min(i + 1, self.n - 1)], t - i)
        c, f = divmod(t, self.n)
        i = int(f)
        a = self.poses[i]
        if i + 1 < self.n:
            b, extra = self.poses[i + 1], 0.0
        else:
            b, extra = self.poses[0], self.stride
        w = f - i
        shift = c * self.stride
        return {j: (_lerp(a[j][0], b[j][0] + extra, w) + shift, _lerp(a[j][1], b[j][1], w)) for j in JOINTS}

    def seconds(self):
        return self.n / self.fps


def _load_track(name):
    path = os.path.join(LIB, name, "motion.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _walk(name):
    m = _load_track(name)
    J = m["joints"]
    n, stride = m["frames"], m["stats"]["stride_per_cycle"]
    poses = [{j: tuple(J[j][i]) for j in JOINTS} for i in range(n)]
    return Clip(name, _lock_toes(poses, stride), m["fps"], True, "side", stride=stride)


def _lock_toes(poses, stride, tol=0.013):
    """The P3 tracks turn the foot about the ankle while the heel lifts, so the toe tip slides
    back ~1.5 cm a frame on the ground. Pin the toe where it first touched down (the foot now
    pivots on the toe, as real feet do) and re-solve the knee. Done on three unrolled cycles so
    contacts across the loop seam are handled; the middle cycle is kept."""
    n = len(poses)
    run = [{j: (u + k * stride, v) for j, (u, v) in p.items()} for k in range(3) for p in poses]
    fade = 5                                   # frames to hand the foot back to the track after lift-off
    for s in "lr":
        low = min(p[f"{s}_toe"][1] for p in run)
        pin, d, since = None, 0.0, fade
        for p in run:
            toe = p[f"{s}_toe"]
            if toe[1] - low > tol:
                pin = None
                since += 1
                shift = d * max(0.0, 1 - since / fade)     # ease the offset out, no jump at lift-off
            else:
                if pin is None:
                    pin = toe[0] + (d * max(0.0, 1 - (since + 1) / fade))
                d = pin - toe[0]
                since = 0
                shift = d
            if abs(shift) < 1e-6:
                continue
            ankle = (p[f"{s}_ankle"][0] + shift, p[f"{s}_ankle"][1])
            p[f"{s}_toe"] = (toe[0] + shift, toe[1])
            p[f"{s}_ankle"] = ankle
            p[f"{s}_knee"] = _leg_ik(p[f"{s}_hip"], ankle, +1)
    return [{j: (u - stride, v) for j, (u, v) in p.items()} for p in run[n:2 * n]]


def _moving_average(xs, k):
    out = []
    for i in range(len(xs)):
        w = xs[max(0, i - k): i + k + 1]
        out.append(sum(w) / len(w))
    return out


def _wave(exaggerate=2.2):
    """Project 3 wave (from my video). The video forearm swings only ~±10° around its raised angle;
    a stick figure needs exaggeration, so the swing is amplified around its running mean and the
    upper arm lifts a little while the hand is up."""
    m = _load_track("wave")
    fore = m["deltas"]["forearm_l"]
    upper = m["deltas"]["upper_arm_l"]
    base = _moving_average(fore, 10)
    poses = []
    for i in range(m["frames"]):
        lift = smooth(base[i] / 110)
        f = base[i] * (1 + 0.25 * lift) + exaggerate * lift * (fore[i] - base[i])
        u = upper[i] + 50 * lift
        poses.append(front_pose(arms={"l": (u, f), "r": (-2, -3)}))
    return Clip("wave", poses, m["fps"], False, "front")


def _idle(seconds=4.0):
    """Breathing and a slow weight shift (loops)."""
    poses = []
    n = int(seconds * FPS)
    for i in range(n):
        w = 2 * math.pi * i / n
        poses.append(front_pose(pelvis=(0.02 * math.sin(w), FRONT_V - 0.006 + 0.006 * math.cos(2 * w)),
                                tilt=-1.5 * math.sin(w), head=3 * math.sin(w + 0.6),
                                arms={"l": (3 * math.sin(w), 4 * math.sin(w - 0.4)),
                                      "r": (-3 * math.sin(w + 0.3), -4 * math.sin(w - 0.1))}))
    return Clip("idle", poses, FPS, True, "front")


def _keyed(keys, t):
    """Spline through (time, value) keys, like an animator's F-curve: Catmull-Rom tangents so the
    motion flows through the middle keys; it starts and ends at rest. Tangents are clamped at
    turning points so it never overshoots a key."""
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]

    def slope(i):
        if i == 0 or i == len(keys) - 1:
            return 0.0
        (ta, va), (tb, vb), (tc, vc) = keys[i - 1], keys[i], keys[i + 1]
        if (vb - va) * (vc - vb) <= 0:
            return 0.0                               # a peak or a dip: stop there, don't overshoot
        return (vc - va) / (tc - ta)

    for i in range(len(keys) - 1):
        (t0, v0), (t1, v1) = keys[i], keys[i + 1]
        if t <= t1:
            h = t1 - t0
            u = (t - t0) / h
            m0, m1 = slope(i) * h, slope(i + 1) * h
            return ((2 * u ** 3 - 3 * u ** 2 + 1) * v0 + (u ** 3 - 2 * u ** 2 + u) * m0 +
                    (-2 * u ** 3 + 3 * u ** 2) * v1 + (u ** 3 - u ** 2) * m1)
    return keys[-1][1]


def _look_down(seconds=2.5):
    """Side view: the head drops, shoulders round, arms hang a little forward; then holds."""
    poses = []
    for i in range(int(seconds * FPS)):
        t = i / FPS
        k = lambda *kv: _keyed(list(zip(kv[::2], kv[1::2])), t)   # noqa: E731
        d = k(0.0, 0.0, 0.6, 1.0)
        breathe = 0.004 * math.sin(2 * math.pi * t / 2.5) * d
        poses.append(side_pose(pelvis=(-0.02 * d, STAND_V - 0.01 * d + breathe), lean=10 * d, head=42 * d,
                               arms={"l": (-4 + 10 * d, 6 + 14 * d), "r": (4 + 8 * d, 14 + 12 * d)}))
    return Clip("look_down", poses, FPS, False, "side")


def _react(seconds=1.75):
    """Side view fright: a tiny anticipation, a fast flinch back with the hands flying up, an
    overshoot, then a trembling hold. Feet stay planted; the knees take the dip."""
    poses = []
    for i in range(int(seconds * FPS)):
        t = i / FPS
        k = lambda *kv: _keyed(list(zip(kv[::2], kv[1::2])), t)   # noqa: E731
        lean = k(0.0, 0.0, 0.12, 3.0, 0.34, -18.0, 0.5, -13.0, 0.8, -10.0)
        head = k(0.0, 0.0, 0.12, 3.0, 0.34, -16.0, 0.6, -8.0)
        back = k(0.0, 0.0, 0.12, 0.02, 0.34, -0.1, 0.6, -0.07)
        dip = k(0.0, 0.0, 0.12, 0.03, 0.34, 0.07, 0.6, 0.05)
        up = k(0.0, 0.0, 0.12, -6.0, 0.36, 150.0, 0.52, 130.0, 0.8, 120.0)
        fore = k(0.0, 0.0, 0.12, 0.0, 0.36, 175.0, 0.52, 160.0, 0.8, 150.0)
        tremble = 3 * math.sin(2 * math.pi * 7 * t) * smooth((t - 0.6) / 0.2) * math.exp(-max(t - 0.6, 0) * 1.5)
        poses.append(side_pose(pelvis=(back, STAND_V - dip), lean=lean + tremble * 0.4, head=head,
                               arms={"l": (up + tremble, fore + tremble), "r": (up - 12 - tremble, fore - 8)},
                               feet={"l": 0.05, "r": -0.08}))
    return Clip("react", poses, FPS, False, "side")


SETTLE_U = 0.25        # how far the pelvis moves forward while settling (leg units)


def _settle(last, n):
    """End a walk: the front foot stays planted, the back foot lifts and steps up beside it, the
    body comes up over the feet. Knees are re-solved so the legs keep their length."""
    front = "l" if last["l_ankle"][0] >= last["r_ankle"][0] else "r"
    back = "r" if front == "l" else "l"
    fu = last[f"{front}_ankle"][0]
    stand = side_pose(pelvis=(fu - 0.05, STAND_V), feet={front: fu, back: fu - 0.1})
    out = []
    a = last[f"{front}_ankle"]
    flat = _add(a, _dir(-30), FOOT)
    for k in range(n):
        p = lerp_pose(last, stand, smooth((k + 1) / n))
        # first the front foot rolls flat (the heel stays put) ...
        tf = smooth((k + 1) / 3)
        p[f"{front}_ankle"] = a
        p[f"{front}_toe"] = (last[f"{front}_toe"][0], _lerp(last[f"{front}_toe"][1], flat[1], tf))
        # ... then the back foot lifts and steps up beside it
        tb = min(max((k - 1) / (n - 2), 0.0), 1.0)
        lift = 0.1 * math.sin(math.pi * tb)
        for j in (f"{back}_knee", f"{back}_ankle", f"{back}_toe"):
            x = _lerp(last[j][0], stand[j][0], smooth(tb))
            v = _lerp(last[j][1], stand[j][1], smooth(tb)) + (lift / 2 if j.endswith("knee") else lift)
            p[j] = (x, v)
        # knees are interpolated, not re-solved: IK on a nearly straight leg snaps
        out.append(p)
    return out


_CACHE = {}


def clip(name):
    if name not in _CACHE:
        if name in WALKS:
            _CACHE[name] = _walk(name)
        else:
            _CACHE[name] = {"wave": _wave, "idle": _idle, "look_down": _look_down, "react": _react}[name]()
    return _CACHE[name]


def ground(pose):
    """Lowest foot point (toe or ankle) height, in leg units."""
    return min(pose[j][1] for j in ("l_toe", "r_toe", "l_ankle", "r_ankle"))


# ---------------------------------------------------------------- figure timeline

class Figure:
    """Where a figure is and what it does, frame by frame, in world metres.

    World pose: joint → (x, depth y, z). The figure lives in the picture plane (x, z); its depth y
    is its layer, and limbs on the far side sit slightly behind (drawn behind, in a lighter tone)."""

    def __init__(self, name, x, y, height=1.7, facing="front", radius=None, start=1):
        self.name = name
        self.L = height / HEAD_TOP_V
        self.r = radius or 0.03 * height / 1.7
        self.y = y
        self.x = x
        self.facing = facing
        self.poses = {}                     # frame → world pose
        self.local = {}                     # frame → (local pose, view)
        self.segments = []
        view = "front" if facing == "front" else "side"
        self.initial = (rest_pose(view), view, facing, x)
        self._put(start, *self.initial)
        self.end = start

    # -- mapping
    def world(self, pose, view, facing, x0):
        base = ground(pose)
        out = {}
        for j, (u, v) in pose.items():
            if view == "side":
                sign = 1 if facing == "right" else -1
                x = x0 + sign * u * self.L
                far = j.startswith("l_") if facing == "right" else j.startswith("r_")
                near = j.startswith("r_") if facing == "right" else j.startswith("l_")
                dy = 0.05 if far else -0.05 if near else 0.0
            else:
                x = x0 + u * self.L
                dy = -0.05 if j[2:] in ("shoulder", "elbow", "wrist") else 0.0
            out[j] = (round(x, 4), round(self.y + dy, 4), round((v - base) * self.L + self.r, 4))
        return out

    def _put(self, frame, pose, view, facing, x0):
        self.local[frame] = (pose, view, facing, x0)
        self.poses[frame] = self.world(pose, view, facing, x0)

    @staticmethod
    def _feet_x(world):
        return (world["l_ankle"][0] + world["r_ankle"][0]) / 2

    @staticmethod
    def _feet_u(pose):
        return (pose["l_ankle"][0] + pose["r_ankle"][0]) / 2

    def pelvis_x(self, frame=None):
        return self.poses[self.end if frame is None else frame]["pelvis"][0]

    def bounds_x(self, frame=None):
        p = self.poses[self.end if frame is None else frame]
        xs = [q[0] for q in p.values()]
        return min(xs) - self.r, max(xs) + self.r

    # -- playing actions
    def play(self, action, start=None, cycles=None, seconds=None, to_x=None, distance=None, direction=None,
             speed=1.0, fps=24, blend=None):
        """Append (or, if start is earlier, replace from `start` on) one action. Returns a summary."""
        c = clip(action)
        first = not self.segments
        s = start if start is not None else (self.end + 1 if not first else min(self.poses))
        if s < min(self.poses):
            raise ValueError(f"start_frame {s} is before the figure exists (frame {min(self.poses)})")
        # drop everything from s on (re-planning), keep the pose right before as the blend source
        prev_f = max(f for f in self.poses if f < s) if any(f < s for f in self.poses) else None
        for f in [f for f in self.poses if f >= s]:
            del self.poses[f], self.local[f]
        self.segments = [g for g in self.segments if g["start"] < s]
        for g in self.segments:
            g["end"] = min(g["end"], s - 1)
        if prev_f is None:
            prev_f = s
            self._put(s, *self.initial)
        hold_from = prev_f
        prev_pose, prev_view, prev_facing, prev_x = self.local[prev_f]

        # facing for this action
        if c.view == "front":
            facing = "front"
        else:
            facing = direction or (prev_facing if prev_facing in ("left", "right") else "right")
        # the new action starts where the feet are (not the pelvis: a flinch leaves it behind them)
        sign = -1 if facing == "left" else 1
        x0 = self._feet_x(self.poses[prev_f]) - sign * self.L * self._feet_u(c.at(0))
        if action in WALKS and to_x is not None:
            facing = "right" if to_x >= x0 else "left"
            sign = -1 if facing == "left" else 1
            x0 = self._feet_x(self.poses[prev_f]) - sign * self.L * self._feet_u(c.at(0))
        note = ""
        rate = c.fps * speed / fps              # clip frames per scene frame
        if action in WALKS:
            step = c.stride / 2 * self.L         # metres per step (half a cycle)
            if to_x is not None:
                d = to_x - x0
                facing = "right" if d >= 0 else "left"
                d = abs(d)
            elif distance is not None:
                d = distance
            else:
                d = None
            if d is not None:
                d = max(d - SETTLE_U * self.L, 0.05)     # the settle step carries the body on a little
                steps = max(1, round(d / step))
                scale = d / (steps * step)
                if steps == 1 and scale < 0.4:
                    raise ValueError(f"the figure is already there ({d:.2f} m away); no need to walk")
            else:
                if seconds is not None:
                    steps = max(1, round(seconds * fps * rate / c.half))
                else:
                    steps = 2 * (cycles if cycles is not None else 2)
                scale = 1.0
            total = steps * c.half               # clip frames
            n = int(round(total / rate)) + 1
            ts = [min(i * rate, total) for i in range(n)]
            local = []
            for t in ts:
                p = c.at(t)
                local.append({j: (u * scale, v) for j, (u, v) in p.items()})
            if abs(scale - 1) > 0.02:
                note = f"steps stretched x{scale:.2f} to land exactly"
            # settle: the walk ends on a contact pose (feet apart); bring the feet together and
            # stand up, as an animator would finish a walk
            local += _settle(local[-1], max(4, round(0.4 * fps)))
            settle = len(local) - n
            n = len(local)
        else:
            if seconds is not None:
                n = max(2, int(round(seconds * fps)))
            elif cycles is not None and c.loop:
                n = int(round(cycles * c.n / rate))
            else:
                n = int(round((c.n - 1) / rate)) + 1
            local = [c.at(i * rate) for i in range(n)]

        # hold the previous pose until the action starts
        for f in range(hold_from + 1, s):
            self._put(f, prev_pose, prev_view, prev_facing, prev_x)
        src = self.poses[s - 1] if (s - 1) in self.poses else self.poses[prev_f]
        if blend is None:
            if first and s == min(self.poses):
                blend = 0
            else:
                # long enough that no joint has to whip across: an eased blend over B frames peaks
                # at 6·d/B² of acceleration, kept under ~3 cm/frame² (0.25-0.7 s at 24 fps)
                w0 = self.world(local[0], c.view, facing, x0)
                d = max(math.dist(src[j], w0[j]) for j in w0)
                blend = min(max(math.ceil(math.sqrt(6 * d / 0.03) * fps / 24), 6 if facing == prev_facing else 8),
                            round(0.7 * fps))
        blend = min(blend, n - 1)
        if blend and action not in WALKS:
            # turn (or settle) into the action's first pose first, then play it: a fright that
            # starts mid-turn reads as a glitch
            local = [local[0]] * blend + local
            n = len(local)
        # map to world; during the blend, cross-fade from the held pose (an in-between: a turn, a settle)
        for i, pose in enumerate(local):
            f = s + i
            w = self.world(pose, c.view, facing, x0)
            if i < blend:
                t = smooth((i + 1) / (blend + 1))
                w = {j: tuple(round(_lerp(a, b, t), 4) for a, b in zip(src[j], w[j])) for j in w}
            self.local[f] = (pose, c.view, facing, x0)
            self.poses[f] = w
        self.end = s + n - 1
        self.facing = facing
        self.x = x0
        seg = {"action": action, "start": s, "end": self.end, "facing": facing, "speed": speed,
               "blend": [s, s + blend - 1] if blend else None}
        if action in WALKS:
            seg["settle"] = [self.end - settle + 1, self.end]
        self.segments.append(seg)
        out = {"name": self.name, "action": action, "frames": [s, self.end], "facing": facing,
               "start_x": round(x0, 2), "end_x": round(self.pelvis_x(), 2),
               "seconds": round(n / fps, 2)}
        if note:
            out["note"] = note
        return out

    def frames(self, last):
        """Poses for every frame up to `last` (holding the final pose)."""
        out = {}
        f0 = min(self.poses)
        cur = self.poses[f0]
        for f in range(f0, max(last, self.end) + 1):
            cur = self.poses.get(f, cur)
            out[f] = cur
        return out
