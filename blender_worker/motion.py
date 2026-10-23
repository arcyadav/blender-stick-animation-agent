"""Stick-figure motion in 2D (pure Python, no bpy, so it is testable outside Blender).

Poses are dicts joint → (u, v) in leg-length units (hip → ankle = 1), v up from the ground.
  side view : u = forward (the way the figure faces)
  front view: u = screen-right (the figure's own left), the figure faces the camera
Sources:
  walk, walk_happy, walk_sad, walk_worried : Project 3 joint tracks (side view, code keyframes)
  wave                                     : Project 3 rotations from my own video (front view)
  idle, look_down, react, run              : keyed here, exaggerated for a stick figure
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
STAND_V = 1.196                      # pelvis height standing: legs straight (feet 0.05 either side)
FRONT_V = 1.19                       # facing the camera: legs straight and a little apart (an upside-down V)
ARM_SCALE = 1.2                      # arms drawn 20% longer than the P3 skeleton's
ARM_SWING = 1.8                      # walks: arm swing x1.8 the P3 tracks
MOOD_BOW = {"walk_sad": (14, 24), "walk_worried": (6, 10)}     # (neck, head) bend for mood walks
WALK_TEMPO = 1.3                     # P3 walks played this much faster (a normal, not a strolling, pace)
HIP_W, SHOULDER_W = 0.045, 0.035     # front view half-widths (limbs spring from near one point)
HEAD_TOP_V = STAND_V + SPINE + NECK + HEAD - 0.075   # standing height above the ground

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "motions")
WALKS = ["walk", "walk_happy", "walk_sad", "walk_worried"]
TRAVELS = WALKS + ["run"]            # cyclic actions that move the figure along
ACTIONS = TRAVELS + ["wave", "idle", "look_down", "react", "sigh", "handshake", "pick_up", "put_down"]
VIEW = {**{w: "side" for w in TRAVELS}, "wave": "front", "idle": "front", "look_down": "side", "react": "side",
        "sigh": "side", "handshake": "side", "pick_up": "side", "put_down": "side"}
GRAB_AT = 0.62            # s into pick_up / put_down when the hand closes / opens
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


def smoother(t):
    """Quintic ease: starts and ends with no speed and no acceleration (no jolt at either end)."""
    t = min(max(t, 0.0), 1.0)
    return t * t * t * (t * (6 * t - 15) + 10)


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

def side_pose(pelvis=(0.0, STAND_V), lean=0.0, head=0.0, arms=None, feet=None, neck=0.0):
    """Standing profile. Angles in degrees: lean (upper body), neck and head > 0 bend forward, each
    on top of the one below; arm angles are measured from hanging straight down, > 0 swings forward.
    feet = ankle u per side."""
    arms = arms or {"l": (-4, 6), "r": (4, 14)}
    feet = feet or {"l": 0.05, "r": -0.05}
    up = 90 - lean
    chest = _add(pelvis, _dir(up), SPINE)
    nk = _add(chest, _dir(up - neck), NECK)
    p = {"pelvis": pelvis, "chest": chest, "neck": nk, "head_top": _add(nk, _dir(up - neck - head), HEAD)}
    neck = nk
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


def front_pose(pelvis=(0.0, FRONT_V), tilt=0.0, head=0.0, arms=None, stance=0.12):
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


def longer_arms(pose, k=ARM_SCALE):
    """Stick figures read better with long arms (fingertips to mid-thigh): the P3 skeleton's
    upper arm and forearm are stretched by k, keeping every joint angle."""
    p = dict(pose)
    for s in "lr":
        sh, el, wr = pose[f"{s}_shoulder"], pose[f"{s}_elbow"], pose[f"{s}_wrist"]
        e = (sh[0] + (el[0] - sh[0]) * k, sh[1] + (el[1] - sh[1]) * k)
        p[f"{s}_elbow"] = e
        p[f"{s}_wrist"] = (e[0] + (wr[0] - el[0]) * k, e[1] + (wr[1] - el[1]) * k)
    return p


def lerp_pose(a, b, t):
    return {j: (_lerp(a[j][0], b[j][0], t), _lerp(a[j][1], b[j][1], t)) for j in JOINTS}


# ---------------------------------------------------------------- clips

class Clip:
    """A library action: a list of poses at `fps`. Walks also carry stride (u per cycle), and the
    frames of half a cycle (a step ending on a contact pose, both feet down)."""

    def __init__(self, name, poses, fps, loop, view, stride=0.0, base=None):
        self.name, self.poses, self.fps, self.loop, self.view, self.stride = name, poses, fps, loop, view, stride
        self.n = len(poses)
        self.half = self.n / 2 if stride else None
        # ground height of the clip (leg units) when it has frames in the air (a run's flight phase);
        # None: every frame stands on its lowest foot
        self.base = base

    def at(self, t):
        """Pose at clip frame t (float). Loops repeat (walks move on by a stride per cycle);
        one-shot clips hold their last pose."""
        if not self.loop:
            t = min(max(t, 0.0), self.n - 1)
            i = min(int(t), self.n - 2) if self.n > 1 else 0
            return lerp_pose(self.poses[i], self.poses[min(i + 1, self.n - 1)], t - i)
        c, f = divmod(t, self.n)
        if getattr(self, "exact", None):
            p = self.exact(f)
            return {j: (u + c * self.stride, v) for j, (u, v) in p.items()}
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
    # P3's walks take 1.5 s a cycle, a slow stroll; played at WALK_TEMPO a normal walk is ~1.15 s
    poses = [_bow(_swing_arms(p), *MOOD_BOW.get(name, (0, 0))) for p in poses]
    return Clip(name, _lock_toes(poses, stride), m["fps"] * WALK_TEMPO, True, "side", stride=stride)


def _rot(v, deg):
    a = math.radians(deg)
    return v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a)


def _bow(pose, neck, head):
    """Bend the neck forward by `neck` degrees and the head a further `head` (side view, facing +u)."""
    if not (neck or head):
        return pose
    p = dict(pose)
    c, n, t = pose["chest"], pose["neck"], pose["head_top"]
    n2 = _add(c, _rot((n[0] - c[0], n[1] - c[1]), -neck))
    p["neck"] = n2
    p["head_top"] = _add(n2, _rot((t[0] - n[0], t[1] - n[1]), -(neck + head)))
    return p


def _swing_arms(pose, k=ARM_SWING, bend=1.2):
    """The P3 walks swing the arms only ~±10°; a stick figure needs more (exaggeration): each
    upper arm's angle from hanging is scaled by k, the elbow bend by `bend`."""
    p = dict(pose)
    for s in "lr":
        sh, el, wr = pose[f"{s}_shoulder"], pose[f"{s}_elbow"], pose[f"{s}_wrist"]
        up = math.atan2(el[0] - sh[0], sh[1] - el[1])          # 0 = hanging, > 0 = forward
        fo = math.atan2(wr[0] - el[0], el[1] - wr[1])
        up2 = up * k
        fo2 = up2 + (fo - up) * bend
        e = (sh[0] + UPPER * math.sin(up2), sh[1] - UPPER * math.cos(up2))
        p[f"{s}_elbow"] = e
        p[f"{s}_wrist"] = (e[0] + FORE * math.sin(fo2), e[1] - FORE * math.cos(fo2))
    return p


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


def _look_down(pitch=50.0, seconds=2.5):
    """Side view: looks down at something `pitch` degrees below eye level. Looking is the neck and
    head (45% / 50%); the body stays upright (a forward-bending torso reads as a bow), the legs
    straight, the arms hanging. Then holds, breathing."""
    poses = []
    for i in range(int(seconds * FPS)):
        t = i / FPS
        d = _keyed([(0.0, 0.0), (0.15, 0.08), (0.7, 1.0)], t)
        breathe = 0.003 * math.sin(2 * math.pi * t / 2.5) * d
        poses.append(side_pose(pelvis=(-0.01 * d, STAND_V), lean=0.05 * pitch * d + breathe * 100,
                               neck=0.45 * pitch * d, head=0.5 * pitch * d,
                               arms={"l": (-3, 3), "r": (3, 7)}))     # arms just hang: not reaching for it
    return Clip("look_down", poses, FPS, False, "side")


# Run foot cycle. The heel rises over the second half of the stance and the start of the swing
# while the toe stays put (push-off); then the foot trails, whips through and lands ahead: the heel
# kicks up behind, the knee drives it forward, the toe lifts so the heel lands first, with no speed.
HEEL_UP = 75.0                                                            # push-off ends at -30-75°
SWING_X = [(0.0, 0.0), (0.3, 0.1), (0.7, 0.8), (1.0, 1.0)]                 # share of the way
SWING_V = [(0.0, ANKLE_V - 0.125 + FOOT * math.sin(math.radians(30 + HEEL_UP))),
           (0.2, 0.62), (0.55, 0.5), (0.85, 0.3), (1.0, ANKLE_V)]          # ankle height
SWING_TOE = [(0.0, -30.0 - HEEL_UP), (0.25, -100.0), (0.6, -55.0), (0.88, -12.0), (1.0, -30.0)]


def _run_pose(f, n=16, stride=2.4, duty=0.35):
    """Run pose at cycle time f (frames, any real number in [0, n)), so playback never has to
    interpolate between stored frames (that let a landing foot creep)."""
    reach = duty * stride / 2                     # ankle ahead of the pelvis at touch-down
    pel_u = stride * f / n
    pel_v = 1.03 - 0.03 * math.cos(2 * math.pi * 2 * (f / n - duty / 2))
    feet, toes, phase = {}, {}, {}
    for s, off in (("l", 0.0), ("r", 0.5)):
        k, ph = divmod(f / n + off, 1.0)
        land = stride * (k - off) + reach
        h0, p1 = 0.5 * duty, duty + 0.12 * (1 - duty)   # heel rise from mid-stance into early swing
        toe0 = _add((land, ANKLE_V), _dir(-30), FOOT)
        if ph < h0:                               # stance: flat, planted where it landed
            ankle, ang = (land, ANKLE_V), -30.0
        elif ph < p1:                             # push-off: pivot on the toe, heel up
            ang = -30 - HEEL_UP * smooth((ph - h0) / (p1 - h0))
            ankle = _add(toe0, _dir(ang), -FOOT)
        else:                                     # swing: heel kicks up, knee drives, foot reaches ahead
            u = (ph - p1) / (1 - p1)
            x0 = toe0[0] - FOOT * math.cos(math.radians(30 + HEEL_UP))
            ankle = (x0 + (land + stride - x0) * _keyed(SWING_X, u), _keyed(SWING_V, u))
            ang = _keyed(SWING_TOE, u)
        feet[s], toes[s], phase[s] = ankle, _add(ankle, _dir(ang), FOOT), ph
    sw = {s: -math.cos(2 * math.pi * phase[s]) for s in "lr"}     # +1 when that leg is behind
    arms = {s: (40 * sw[s], 40 * sw[s] + 95) for s in "lr"}       # arm forward when its leg is back
    p = side_pose(pelvis=(pel_u, pel_v), lean=14, head=-10, arms=arms)
    for s in "lr":
        p[f"{s}_hip"] = p["pelvis"]
        p[f"{s}_ankle"], p[f"{s}_toe"] = feet[s], toes[s]
        p[f"{s}_knee"] = _leg_ik(p["pelvis"], feet[s], +1)
    return p


def _run(n=16, stride=2.4):
    """Side-view run cycle, keyed from foot paths like P3's walk: each foot is planted for part of
    the cycle (so it can't slide), then kicks up behind, drives the knee forward and lands ahead;
    there is a flight phase with both feet off the ground. Body leans forward, arms bent ~90° pump
    against the legs, the pelvis dips at mid-stance and rises in flight."""
    c = Clip("run", [_run_pose(f, n, stride) for f in range(n)], FPS, True, "side", stride=stride,
             base=ANKLE_V + FOOT * math.sin(math.radians(-30)))
    c.exact = lambda t: _run_pose(t, n, stride)
    return c


def _ik(root, target, l1, l2, bend):
    """Two-bone IK: the middle joint for a chain root→target; bend = +1 puts it toward +u."""
    dx, dy = target[0] - root[0], target[1] - root[1]
    d = math.hypot(dx, dy) or 1e-6
    if d >= (l1 + l2) * 0.9999:
        return _add(root, (dx / d, dy / d), l1)
    a = (l1 ** 2 - l2 ** 2 + d * d) / (2 * d)
    h = math.sqrt(max(l1 ** 2 - a * a, 0.0))
    mx, my = root[0] + dx * a / d, root[1] + dy * a / d
    px, py = -dy / d, dx / d
    if px * bend < 0:
        px, py = -px, -py
    return mx + px * h, my + py * h


HAND_V = 1.4          # handshake height (leg units above the toe line): about waist height


def _handshake(reach=0.5, seconds=2.0):
    """Side view: reach the right hand out to a point `reach` ahead of the feet (half way to the
    partner, who does the same, so the hands meet), three pumps, let go. The elbow stays bent below."""
    poses = []
    rest = side_pose()
    for i in range(int(seconds * FPS)):
        t = i / FPS
        out = _keyed([(0.0, 0.0), (0.45, 1.0), (1.45, 1.0), (1.9, 0.0)], t)
        pump = 0.05 * math.sin(2 * math.pi * 3 * (t - 0.45) / 1.0) * (0.45 < t < 1.45)
        p = side_pose(lean=3 * out, head=-2 * out)
        sh = p["r_shoulder"]
        target = (reach, HAND_V + pump)
        # the arm is drawn ARM_SCALE longer about the shoulder: aim the unscaled arm at a scaled-in target
        aim = (sh[0] + (target[0] - sh[0]) / ARM_SCALE, sh[1] + (target[1] - sh[1]) / ARM_SCALE)
        el = _ik(sh, aim, UPPER, FORE, -1)                         # elbow bends down/back
        reach_pose = dict(p, r_elbow=el, r_wrist=aim)
        poses.append(lerp_pose(dict(p, r_elbow=rest["r_elbow"], r_wrist=rest["r_wrist"]), reach_pose, out))
    return Clip("handshake", poses, FPS, False, "side")


CARRY_SWING = (2.0, 14.0)  # carrying at the side: the arm hangs, the elbow a little bent, and
                           # the walk swings it (the thing swings along in the hand)
CARRY = (24.0, 108.0)     # carrying, side view: upper arm hangs by the body (10° forward), the forearm
                          # comes up to just above level in front, holding the thing at the waist


def _arm_angles(p, side):
    """(upper, forearm) angles in degrees from hanging straight down, > 0 = forward."""
    sh, el, wr = p[f"{side}_shoulder"], p[f"{side}_elbow"], p[f"{side}_wrist"]
    return (math.degrees(math.atan2(el[0] - sh[0], sh[1] - el[1])),
            math.degrees(math.atan2(wr[0] - el[0], el[1] - wr[1])))


def _set_arm(p, side, upper, fore):
    sh = p[f"{side}_shoulder"]
    el = (sh[0] + UPPER * math.sin(math.radians(upper)), sh[1] - UPPER * math.cos(math.radians(upper)))
    wr = (el[0] + FORE * math.sin(math.radians(fore)), el[1] - FORE * math.cos(math.radians(fore)))
    return dict(p, **{f"{side}_elbow": el, f"{side}_wrist": wr})


def _reach_angles(p, side, target):
    """Arm angles that put the hand on target (u, v). The arm is drawn ARM_SCALE longer about the
    shoulder, so the unscaled arm aims at a target pulled in by that factor. Of the two elbow
    solutions, the one that bends like an elbow (forearm forward of the upper arm)."""
    sh = p[f"{side}_shoulder"]
    aim = (sh[0] + (target[0] - sh[0]) / ARM_SCALE, sh[1] + (target[1] - sh[1]) / ARM_SCALE)
    best = None
    for b in (1, -1):
        q = dict(p, **{f"{side}_elbow": _ik(sh, aim, UPPER, FORE, b), f"{side}_wrist": aim})
        u, f = _arm_angles(q, side)
        flex = f - u
        if best is None or (0 <= flex <= 170) > (0 <= best[2] <= 170):
            best = (u, f, flex)
    return best[:2]


def _arm_to(p, side, target):
    return _set_arm(p, side, *_reach_angles(p, side, target))


def _lerp_angles(a, b, t):
    return tuple(_lerp(x, y, t) for x, y in zip(a, b))


def _grip(p):
    """Carrying at the side: keep the right arm's swing, bend the elbow a little more."""
    up, fore = _arm_angles(p, "r")
    return _set_arm(p, "r", up, max(fore, up + 12))


def carry_arm(p, view):
    """While holding something: elbow down by the side, forearm up in front holding it."""
    if view == "front":
        sh = p["r_shoulder"]
        el = _add(sh, _dir(-96), UPPER)
        return dict(p, r_elbow=el, r_wrist=_add(el, _dir(28), FORE))
    return _set_arm(p, "r", *CARRY)


def _reach_pose(target):
    """How to get the right hand to target (u, v): bend at the waist for things up high, squat
    (knees bend, hips go back) for low ones; the least effort that reaches. None if too far."""
    arm = (UPPER + FORE) * ARM_SCALE * 0.97
    best = None
    for drop in [i * 0.025 for i in range(25)]:
        for lean in range(0, 72, 3):
            p = side_pose(pelvis=(-0.15 * drop, STAND_V - drop), lean=lean, head=-0.3 * lean)
            if math.dist(p["r_shoulder"], target) <= arm:
                cost = lean + 50 * drop              # knees do a fair share: a squat, not a stoop
                if best is None or cost < best[0]:
                    best = (cost, drop, lean)
                break
    return None if best is None else best[1:]


def _pick_or_place(target, seconds=1.6, place=False, carry="front"):
    """Side view, by joint angles so the elbow moves like an elbow. Picking: bend/squat while the
    arm reaches to the thing, hold (the grab is at GRAB_AT s), then stand up while the forearm lifts
    it into the carry (elbow down by the side). Placing is the reverse, ending with the arm hanging."""
    reach = _reach_pose(target)
    if reach is None:
        return None
    drop, lean = reach
    hang = _arm_angles(side_pose(), "r")
    poses = []
    for i in range(int(seconds * FPS)):
        t = i / FPS
        d = _keyed([(0.0, 0.0), (0.55, 1.0), (0.8, 1.0), (1.4, 0.0)], t)
        p = side_pose(pelvis=(-0.15 * drop * d, STAND_V - drop * d), lean=lean * d, head=-0.3 * lean * d)
        at = _reach_angles(p, "r", target)      # hand on the thing, for this body pose
        held = CARRY if carry == "front" else CARRY_SWING
        before, after = (held, hang) if place else (hang, held)
        if t <= 0.55:
            arm = _lerp_angles(before, at, smooth(t / 0.55))
        elif t <= 0.8:
            arm = at
        else:
            arm = _lerp_angles(at, after, smooth((t - 0.8) / 0.6))
        poses.append(_set_arm(p, "r", *arm))
    return Clip("put_down" if place else "pick_up", poses, FPS, False, "side")


def _sigh(seconds=2.6):
    """Side view, facing ahead: a breath in (chest up, a slight lean back, the head lifts), then a
    long breath out: the upper body slumps, the neck and head drop, the arms hang loose. Holds sad."""
    poses = []
    for i in range(int(seconds * FPS)):
        t = i / FPS
        k = lambda *kv: _keyed(list(zip(kv[::2], kv[1::2])), t)   # noqa: E731
        lean = k(0.0, 0.0, 0.7, -4.0, 1.7, 9.0)
        neck = k(0.0, 0.0, 0.7, -3.0, 1.7, 14.0)
        head = k(0.0, 0.0, 0.7, -8.0, 1.7, 18.0)
        rise = k(0.0, 0.0, 0.7, 0.012, 1.7, -0.01)
        arm = k(0.0, 0.0, 0.7, -2.0, 1.7, 4.0)
        poses.append(side_pose(pelvis=(0.0, STAND_V + rise), lean=lean, neck=neck, head=head,
                               arms={"l": (-3 + arm, 3 + arm), "r": (3 + arm, 7 + arm)}))
    return Clip("sigh", poses, FPS, False, "side")


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


def _times(total, rate, half):
    """Clip times for each scene frame of a walk/run of `total` clip frames: it picks up speed over
    the first step (from 55%), as a body does from a standstill, and the steps are stretched a
    touch so the last frame lands exactly on the final contact pose (no stalled frame)."""
    ts, t = [0.0], 0.0
    while t < total:
        t += rate * (0.55 + 0.45 * smooth(t / half))
        ts.append(t)
    if len(ts) > 2 and ts[-1] - total > 0.5 * (ts[-1] - ts[-2]):
        ts.pop()                                  # closer to land one frame early, stretched
    k = total / ts[-1]
    return [x * k for x in ts]


def _hermite(p0, p1, m0, u):
    """Cubic from p0 (leaving with velocity m0, per unit u) to p1 (arriving at rest)."""
    return ((2 * u ** 3 - 3 * u ** 2 + 1) * p0 + (u ** 3 - 2 * u ** 2 + u) * m0 + (-2 * u ** 3 + 3 * u ** 2) * p1)


def _brake(prev, last, n=9):
    """End a run: one braking step. Every joint leaves the run with the speed it had (no jolt) and
    eases to a stop: the body travels on about speed·n/2, the swinging foot comes through and lands
    under it, the lean and the pumping arms relax. The planted foot stays put; _settle then brings
    it alongside."""
    front = "l" if last["l_ankle"][0] >= last["r_ankle"][0] else "r"
    swing = "r" if front == "l" else "l"
    speed = last["pelvis"][0] - prev["pelvis"][0]
    drift = speed * n / 2
    target = side_pose(pelvis=(last["pelvis"][0] + drift, STAND_V - 0.04), lean=4,
                       feet={swing: last["pelvis"][0] + drift + 0.15, front: last[f"{front}_ankle"][0]})
    out = []
    for k in range(n):
        u = (k + 1) / n
        p = {}
        for j in JOINTS:
            vel = [(a - b) * n for a, b in zip(last[j], prev[j])]
            p[j] = tuple(_hermite(last[j][i], target[j][i], vel[i], u) for i in (0, 1))
        p[f"{front}_ankle"], p[f"{front}_toe"] = last[f"{front}_ankle"], last[f"{front}_toe"]
        a = p[f"{swing}_ankle"]
        p[f"{swing}_ankle"] = (a[0], max(a[1], ANKLE_V))
        t = p[f"{swing}_toe"]
        p[f"{swing}_toe"] = (t[0], max(t[1], ANKLE_V - FOOT * 0.5))
        for s in "lr":
            p[f"{s}_hip"] = p["pelvis"]
            p[f"{s}_knee"] = _leg_ik(p["pelvis"], p[f"{s}_ankle"], +1)
        out.append(p)
    return out


_CACHE = {}


def clip(name, **params):
    key = (name, tuple(sorted(params.items())))
    if key not in _CACHE:
        if name in WALKS:
            _CACHE[key] = _walk(name)
        else:
            _CACHE[key] = {"wave": _wave, "idle": _idle, "look_down": _look_down, "react": _react,
                           "run": _run, "handshake": _handshake, "sigh": _sigh}[name](**params)
    return _CACHE[key]


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
        self.r = radius or 0.042 * height / 1.7        # stroke half-width: a bold stick figure
        self.y = y
        self.x = x
        self.facing = facing
        self.poses = {}                     # frame → world pose
        self.local = {}                     # frame → (local pose, view)
        self.segments = []
        view = "front" if facing == "front" else "side"
        self.initial = (rest_pose(view), view, facing, x)
        self.holds = []                     # [{"obj", "from", "to"}]: what the right hand carries, when
        self.holding = None
        self._put(start, *self.initial)
        self.end = start

    # -- mapping
    def world(self, pose, view, facing, x0, base=None):
        base = ground(pose) if base is None else base
        pose = longer_arms(pose)
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

    def start_holding(self, obj, carry="front"):
        """The figure starts the clip with obj already in its right hand."""
        f0 = min(self.poses)
        self.holds.append({"obj": obj, "from": f0, "to": None, "carry": carry, "initial": True})
        self.holding = obj
        pose, view, facing, x0 = self.initial
        held = carry_arm(pose, view) if carry == "front" else _grip(pose)
        self.initial = (held, view, facing, x0)
        self._put(f0, *self.initial)

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
             speed=1.0, fps=24, blend=None, look_at=None, partner_x=None, obj=None, obj_at=None,
             carry="front"):
        """Append (or, if start is earlier, replace from `start` on) one action. Returns a summary.
        look_at = (x, z) of what a look_down looks at: it turns toward it and bends just enough.
        pick_up / put_down: obj = the object's name, obj_at = (x, z) where its centre is / will be."""
        c = None if action in ("pick_up", "put_down") else clip(action)
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
        self.holds = [h for h in self.holds if h["from"] < s or h.get("initial")]
        for h in self.holds:
            if h["to"] is not None and h["to"] >= s:
                h["to"] = None
        self.holding = next((h["obj"] for h in self.holds if h["to"] is None), None)
        style = next((h.get("carry", "front") for h in self.holds if h["to"] is None), "front")
        if prev_f is None:
            prev_f = s
            self._put(s, *self.initial)
        hold_from = prev_f
        prev_pose, prev_view, prev_facing, prev_x = self.local[prev_f]
        if action == "handshake":
            if partner_x is None:
                raise ValueError("handshake needs `to`: the other figure's name")
            fx = self._feet_x(self.poses[prev_f])
            gap = abs(partner_x - fx)
            reach = gap / 2 / self.L
            if not 0.25 <= reach <= 0.75:
                raise ValueError(f"the figures are {gap:.2f} m apart; a handshake needs them "
                                 f"{0.5 * self.L:.1f}-{1.5 * self.L:.1f} m apart: walk closer (or apart) first")
            direction = "right" if partner_x > fx else "left"
            c = clip(action, reach=round(reach, 3))
        if action in ("pick_up", "put_down"):
            if action == "pick_up" and self.holding:
                raise ValueError(f"the figure is already holding '{self.holding}'; put it down first")
            if action == "put_down" and not self.holding:
                raise ValueError("the figure is not holding anything")
            fx = self._feet_x(self.poses[prev_f])
            dx = obj_at[0] - fx
            if abs(dx) > 0.05:
                direction = "right" if dx > 0 else "left"
            elif prev_facing in ("left", "right"):
                direction = prev_facing
            target = (abs(dx) / self.L, (obj_at[1] - self.r) / self.L + ground(rest_pose("side")))
            c = _pick_or_place(target, place=action == "put_down",
                               carry=carry if action == "pick_up" else style)
            if c is None:
                where = "it" if action == "pick_up" else "that spot"
                raise ValueError(f"{where} is {abs(dx):.2f} m away and out of reach; walk to it first "
                                 "(play_action walk with to=...)")
        if action == "look_down" and look_at is not None:
            fx = self._feet_x(self.poses[prev_f])
            dx = look_at[0] - fx
            if abs(dx) > 0.1:
                direction = "right" if dx > 0 else "left"
            eye = (STAND_V + SPINE + NECK + 0.5 * HEAD - 0.075) * self.L
            pitch = math.degrees(math.atan2(eye - look_at[1], max(abs(dx), 0.05)))
            c = clip(action, pitch=round(min(max(pitch, 10.0), 80.0)))

        # facing for this action
        if c.view == "front":
            facing = "front"
        else:
            facing = direction or (prev_facing if prev_facing in ("left", "right") else "right")
        # the new action starts where the feet are (not the pelvis: a flinch leaves it behind them)
        sign = -1 if facing == "left" else 1
        x0 = self._feet_x(self.poses[prev_f]) - sign * self.L * self._feet_u(c.at(0))
        if action in TRAVELS and to_x is not None:
            facing = "right" if to_x >= x0 else "left"
            sign = -1 if facing == "left" else 1
            x0 = self._feet_x(self.poses[prev_f]) - sign * self.L * self._feet_u(c.at(0))
        note, settle = "", 0
        rate = c.fps * speed / fps              # clip frames per scene frame
        brake_n, settle_n = max(6, round(0.38 * fps)), max(4, round(0.4 * fps))
        stop_frames = settle_n + (brake_n if c.base is not None else 0)
        if action in TRAVELS:
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
                # the settle step (and a run's braking step) carries the body on a little
                d = max(d - (SETTLE_U + (0.15 * 0.38 * 24 / 2 + 0.15 if c.base is not None else 0)) * self.L, 0.05)
                steps = max(1, round(d / step))
                scale = d / (steps * step)
                if steps == 1 and d < 0.05:
                    raise ValueError(f"the figure is already there ({d:.2f} m away); no need to walk")
            else:
                if seconds is not None:
                    # the step count whose whole clip (speed-up, steps, stop) is closest to `seconds`
                    want = seconds * fps
                    steps = min(range(1, 200), key=lambda k: abs(len(_times(k * c.half, rate, c.half)) +
                                                                 stop_frames - want))
                else:
                    steps = max(1, round(2 * (cycles if cycles is not None else 2)))
                scale = 1.0
            total = steps * c.half               # clip frames
            ts = _times(total, rate, c.half)
            n = len(ts)
            local = []
            for t in ts:
                p = c.at(t)
                local.append({j: (u * scale, v) for j, (u, v) in p.items()})
            if abs(scale - 1) > 0.02:
                note = f"steps stretched x{scale:.2f} to land exactly"
            # settle: the walk ends on a contact pose (feet apart); bring the feet together and
            # stand up, as an animator would finish a walk
            if c.base is not None:               # a run can't stop dead: one braking step first
                local += _brake(local[-2], local[-1], brake_n)
            local += _settle(local[-1], settle_n)
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

        if self.holding and action not in ("pick_up", "put_down"):
            # "front": the forearm holds it up in front; "swing": the arm keeps its own motion
            # (a walk swings it), just a touch more bent, so the thing swings along
            local = [carry_arm(p, c.view) if style == "front" else _grip(p) for p in local]
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
                w0 = self.world(local[0], c.view, facing, x0, base=c.base)
                d = max(math.dist(src[j], w0[j]) for j in w0)
                blend = min(max(math.ceil(math.sqrt(6 * d / 0.03) * fps / 24), 6 if facing == prev_facing else 8),
                            round(0.7 * fps))
        blend = min(blend, n - 1)
        if blend and action not in TRAVELS:
            # turn (or settle) into the action's first pose first, then play it: a fright that
            # starts mid-turn reads as a glitch
            local = [local[0]] * blend + local
            n = len(local)
        # map to world; during the blend, cross-fade from the held pose (an in-between: a turn, a settle)
        for i, pose in enumerate(local):
            f = s + i
            w = self.world(pose, c.view, facing, x0, base=c.base if i < n - settle else None)
            if i < blend:
                t = smoother((i + 1) / (blend + 1))
                w = {j: tuple(round(_lerp(a, b, t), 4) for a, b in zip(src[j], w[j])) for j in w}
            self.local[f] = (pose, c.view, facing, x0)
            self.poses[f] = w
        self.end = s + n - 1
        self.facing = facing
        self.x = x0
        seg = {"action": action, "start": s, "end": self.end, "facing": facing, "speed": speed,
               "blend": [s, s + blend - 1] if blend else None}
        if action in TRAVELS:
            seg["settle"] = [self.end - settle + 1, self.end]
        self.segments.append(seg)
        if action in ("pick_up", "put_down"):
            grab = s + (blend or 0) + int(round(GRAB_AT * fps))
            if action == "pick_up":
                self.holds.append({"obj": obj, "from": grab, "to": None, "carry": carry})
                self.holding = obj
            else:
                self.holds[-1]["to"] = grab
                self.holding = None
            seg["grab"] = grab
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
