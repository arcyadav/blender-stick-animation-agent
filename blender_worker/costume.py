"""A simple 2D cartoon look on top of a stick figure: the same joints every frame, drawn as a dressed
character (shirt, trousers, shoes, skin, hair) with a face whose mouth follows the action.

Every body part is a thick stroke with round ends drawn whole every frame, so rotating parts never open
gaps (the hidden-area problem of cut-out drawings, Project 3). Far-side limbs are drawn behind the body,
near-side limbs in front. This is a look only: the motion, the tools and the checks are unchanged.
"""
import math

import bpy

import motion

SKIN = (0.96, 0.78, 0.62)
DEFAULT = {"trousers": (0.16, 0.2, 0.32), "shoes": (0.12, 0.1, 0.1), "skin": SKIN, "hair": (0.22, 0.13, 0.08)}
MOODS = {"walk_happy": "smile", "wave": "smile", "handshake": "smile", "walk_sad": "sad", "sigh": "sad",
         "walk_worried": "worried", "react": "o", "walk": "neutral", "run": "neutral"}

# part: (colour key, half-width in stroke radii, depth order: higher is further back)
PARTS = {
    "far_leg": ("trousers", 1.75, 9), "far_shoe": ("shoes", 1.45, 9.5), "far_upper": ("shirt", 1.6, 8),
    "far_fore": ("skin", 1.15, 8.5),
    "near_leg": ("trousers", 1.75, 6), "near_shoe": ("shoes", 1.45, 5.5), "hips": ("trousers", 2.5, 5),
    "torso": ("shirt", 2.9, 4), "neck": ("skin", 1.1, 4.5), "hair": ("hair", 1.0, 3.5), "head": ("skin", 1.0, 3),
    "face": ("ink", 1.0, 2), "near_upper": ("shirt", 1.6, 1), "near_fore": ("skin", 1.15, 0.5)}
# a simple female look adds long hair (behind the head and shoulders) and a skirt that widens to the hem
FEMALE_PARTS = {"long_hair": ("hair", None, 4.6), "skirt": ("skirt", 2.9, 3.9)}   # skirt over the top: tucked in
SKIRT_WIDTH = (1.12, 1.65)                     # waist (as wide as the torso) and hem, times the torso's half-width
FEMALE_WAIST = 0.42                           # her waist (top of the skirt), from pelvis (0) to chest (1)
SKIRT_MIN = 0.32                              # shortest skirt (leg units), e.g. sitting with thighs toward us
FRONT_SWAP = {"far_upper": 4.35, "far_fore": 4.25, "near_upper": 4.35, "near_fore": 4.25}   # from the front: both arms just behind the torso, in front of hips and legs
STEP = 0.006                                  # metres of depth between consecutive layers
DISC = 0.0015
FLAT = 0.02                                   # parts are flattened in depth: flat cut-outs, so the layer order decides


def _mid(a, b, t=0.5):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _disc(c):
    """A very short tube seen end-on: a filled circle. Its depth is its only y (see DISC)."""
    return [(c[0], -DISC, c[2]), (c[0], DISC, c[2])]


def _foot(pose, s, foot_len):
    """The drawn foot as in the stick figure: the front of the ankle→toe bone, laid flat."""
    a, t = pose[f"{s}_ankle"], pose[f"{s}_toe"]
    vx, vz = t[0] - a[0], t[2] - a[2]
    n = math.hypot(vx, vz) or 1.0
    rot = math.radians(30.0 if vx >= 0 else -30.0)
    fx = (vx * math.cos(rot) - vz * math.sin(rot)) / n
    fz = (vx * math.sin(rot) + vz * math.cos(rot)) / n
    return [(t[0] - fx * foot_len, a[1], t[2] - fz * foot_len), t]


def _mood_track(fig, frames):
    """frame → mouth shape; a mood holds through actions that don't set one (idle, sit, look...)."""
    out, mood = {}, "neutral"
    segs = sorted(fig.segments, key=lambda g: g["start"])
    for f in frames:
        for g in segs:
            if g["start"] <= f <= g["end"] and g["action"] in MOODS:
                mood = MOODS[g["action"]]
        out[f] = mood
    return out


def _shapes(fig, pose, view, facing, mood, head_r, foot_len, female=False):
    """Points for every part (lists of strokes) for one frame, before depth is applied."""
    if view == "side":
        far = "l" if facing == "right" else "r"
        near = "r" if far == "l" else "l"
    else:
        far, near = "l", "r"                   # from the front both arms hang in front of the body
    sh = _mid(pose["l_shoulder"], pose["r_shoulder"])
    sh = (sh[0], pose["chest"][1], max(sh[2], pose["chest"][2]))
    nk, top = pose["neck"], pose["head_top"]
    hc = _mid(nk, top)
    up = (top[0] - nk[0], top[2] - nk[2])
    n = math.hypot(*up) or 1.0
    up = (up[0] / n, up[1] / n)
    sign = 1 if facing == "right" else -1
    fwd = (up[1] * sign, -up[0] * sign)        # perpendicular to the head's axis, toward the facing

    def at(du, dv, c=hc):                      # a point on the head: du along fwd, dv along up (head radii)
        return (c[0] + (fwd[0] * du + up[0] * dv) * head_r, c[1], c[2] + (fwd[1] * du + up[1] * dv) * head_r)

    def arm(s):
        shoulder = pose[f"{s}_shoulder"]
        if view != "side":                      # from the front the sleeve starts at the shoulder's edge
            shoulder = _mid(shoulder, pose[f"{s}_elbow"], 0.22)
        return ([[shoulder, pose[f"{s}_elbow"]]],
                [[pose[f"{s}_elbow"], pose[f"{s}_wrist"]], _disc(pose[f"{s}_wrist"])])

    def leg(s):
        # the shoe runs from under the ankle to the toe, so the trouser leg's round end overlaps it
        heel, toe = _foot(pose, s, foot_len)
        a = pose[f"{s}_ankle"]
        under = (a[0], a[1], min(a[2], heel[2] + 0.35 * (a[2] - heel[2])))
        if view != "side":                      # from the front a shoe is a short shape centred under the ankle
            g = min(toe[2], heel[2])
            under, toe = (a[0] - 0.22 * foot_len, a[1], g), (a[0] + 0.22 * foot_len, a[1], g)
        return [[pose[f"{s}_hip"], pose[f"{s}_knee"], a]], [[under, toe]]

    out = {}
    out["far_upper"], out["far_fore"] = arm(far)
    out["near_upper"], out["near_fore"] = arm(near)
    out["far_leg"], out["far_shoe"] = leg(far)
    out["near_leg"], out["near_shoe"] = leg(near)
    if view != "side":                          # front: both legs side by side, at the same depth
        out["far_leg"], out["near_leg"] = out["near_leg"], out["far_leg"]
    pelvis, chest = pose["pelvis"], pose["chest"]
    out["hips"] = [[_mid(pelvis, chest, -0.05), _mid(pelvis, chest, 0.2)]]
    out["torso"] = [[_mid(pelvis, chest, 0.12), _mid(chest, sh, 0.6)]]
    out["neck"] = [[_mid(chest, sh, 0.6), hc]]
    out["head"] = [_disc(hc)]
    back = -0.18 if view == "side" else 0.0
    out["hair"] = [_disc(at(back, 0.16))]
    if female:
        if view == "side":                      # one fall of hair down the back of the head to the shoulders
            strand = [at(-0.5, 0.45), at(-0.95, -0.35), at(-0.8, -1.3)]
            out["long_hair"] = [strand, strand]
        else:                                   # from the front: down both sides of the face
            out["long_hair"] = [[(hc[0] + d * 0.7 * head_r, hc[1], hc[2] + 0.45 * head_r),
                                 (hc[0] + d * 0.98 * head_r, hc[1], hc[2] - 0.35 * head_r),
                                 (hc[0] + d * 0.9 * head_r, hc[1], hc[2] - 1.3 * head_r)] for d in (-1, 1)]
        knees = _mid(pose["l_knee"], pose["r_knee"])
        waist = _mid(pelvis, chest, FEMALE_WAIST)
        hem = _mid(pelvis, knees, 0.8)
        if math.hypot(hem[0] - waist[0], hem[2] - waist[2]) < SKIRT_MIN * fig.L:   # thighs toward us
            hem = (hem[0], hem[1], waist[2] - SKIRT_MIN * fig.L)
        if view == "side":                      # side-on the skirt sits back a little, over the seat
            back_x = -sign * 0.4 * PARTS["torso"][1] * fig.r
            waist, hem = (waist[0] + back_x, waist[1], waist[2]), (hem[0] + back_x, hem[1], hem[2])
        low = pelvis[2] - 1.15 * PARTS["hips"][1] * fig.r       # the hem always covers the hips
        if hem[2] > low:
            hem = (hem[0], hem[1], low)
        out["skirt"] = [[waist, hem]]

    # face: eyes and a mouth (3 points; its middle sets the expression)
    if view == "side":
        eyes = [at(0.48, 0.12), at(0.48, 0.12)]
        a, b = at(0.38, -0.42), at(0.72, -0.34)
        across = (b[0] - a[0], b[2] - a[2])
    else:
        eyes = [(hc[0] - 0.32 * head_r, hc[1], hc[2] + 0.1 * head_r), (hc[0] + 0.32 * head_r, hc[1], hc[2] + 0.1 * head_r)]
        a = (hc[0] - 0.24 * head_r, hc[1], hc[2] - 0.4 * head_r)
        b = (hc[0] + 0.24 * head_r, hc[1], hc[2] - 0.4 * head_r)
    m = _mid(a, b)
    bend = {"smile": -0.16, "sad": 0.12, "worried": 0.06, "neutral": 0.0, "o": 0.0}[mood]
    if mood == "o":                             # a small round open mouth
        a, b = _mid(m, a, 0.8), _mid(m, b, 0.8)
        mid = (m[0], m[1], m[2] - 0.08 * head_r)
    else:
        mid = (m[0] + up[0] * bend * head_r, m[1], m[2] + up[1] * bend * head_r)
    out["face"] = [_disc(eyes[0]), _disc(eyes[1]), [a, mid, b]]
    for part, strokes in out.items():          # round ends and joints: a disc on every stroke point
        if part not in ("head", "hair", "face", "skirt"):
            out[part] = strokes + [_disc(q) for st in strokes if len(st) > 2 or st[0][1] != -DISC for q in st]
    return out


def _radius(part, fig, head_r):
    if part in ("head",):
        return head_r
    if part == "hair":
        return head_r * 1.06
    if part == "face":
        return head_r * 0.11
    if part == "long_hair":
        return head_r * 0.4
    return fig.r * {**PARTS, **FEMALE_PARTS}[part][1]


def dress(name, fig, colour, outfit, frames, appear=None, apply_colour=None, fcurves=None, style=None):
    """Build the costume objects for figure `name` and key them every frame. → list of object names."""
    female = style == "female"
    look = {**DEFAULT, "shirt": tuple(colour), "ink": (0.08, 0.06, 0.06)}
    if female:                                  # bare legs under the skirt, a darker skirt than the top
        look.update({"trousers": SKIN, "skirt": tuple(c * 0.55 for c in colour), "shoes": (0.45, 0.12, 0.15)})
    look.update(outfit or {})
    parts = {**PARTS, **(FEMALE_PARTS if female else {})}
    if female:                                  # her hips are part of the skirt, never bare
        parts["hips"] = ("skirt",) + PARTS["hips"][1:]
    head_r = 0.55 * motion.HEAD * fig.L
    foot_len = 0.5 * motion.FOOT * fig.L * 1.15
    fs = sorted(frames)
    moods = _mood_track(fig, fs)
    per = {}
    for f in fs:
        pose = frames[f]
        _, view, facing, _ = fig.local[f] if f in fig.local else (None, "front", "front", None)
        per[f] = _shapes(fig, pose, view, facing, moods[f], head_r, foot_len, female)
    names = []
    for part, (key, _, order) in parts.items():
        oname = f"{name}__{part}"
        old = bpy.data.objects.get(oname)
        if old:
            bpy.data.objects.remove(old)
        cu = bpy.data.curves.new(oname, "CURVE")
        cu.dimensions = "3D"
        cu.bevel_depth = _radius(part, fig, head_r)
        cu.bevel_resolution = 6
        cu.use_fill_caps = True
        mat = bpy.data.materials.new(oname)
        apply_colour(mat, look[key])
        cu.materials.append(mat)
        first = per[fs[0]][part]
        for stroke in first:
            sp = cu.splines.new("POLY")
            sp.points.add(len(stroke) - 1)
        if part == "face":                      # the mouth is thinner than the eyes
            for p in cu.splines[2].points:
                p.radius = 0.45
        if part == "skirt":                     # narrow at the waist, wide at the hem
            for p, w in zip(cu.splines[0].points, SKIRT_WIDTH):
                p.radius = w
        o = bpy.data.objects.new(oname, cu)
        o["kind"] = "costume"
        o["costume_of"] = name
        bpy.context.scene.collection.objects.link(o)
        o.location = (0.0, fig.y + (order - 5) * STEP, 0.0)
        o.scale = (1.0, FLAT, 1.0)
        for k, sp in enumerate(cu.splines):
            for j, p in enumerate(sp.points):
                x, y, z = first[k][j]
                p.co = (x, (y if abs(y) <= DISC else 0.0) / FLAT, z, 1.0)   # discs keep their tiny depth
                p.keyframe_insert("co", frame=fs[0])
        # from the front both arms hang just behind the body (in front of the hips and legs, for hands on knees)
        shift = {f: ((FRONT_SWAP[part] - order) * STEP / FLAT
                     if part in FRONT_SWAP and (fig.local[f][1] if f in fig.local else "front") != "side" else 0.0)
                 for f in fs}
        curves = {(fc.data_path, fc.array_index): fc for fc in fcurves(cu)}
        for k, sp in enumerate(cu.splines):
            for j, _ in enumerate(sp.points):
                for a in (0, 1, 2):
                    fc = curves.get((f"splines[{k}].points[{j}].co", a))
                    if fc is None:
                        continue
                    fc.keyframe_points.add(len(fs) - 1)
                    co = []
                    for f in fs:
                        v = per[f][part][k][j][a]
                        if a == 1:
                            v = (v if abs(v) <= DISC else 0.0) / FLAT + shift[f]
                        if a == 2 and appear and f < appear:
                            v -= 100.0
                        co += [f, v]
                    fc.keyframe_points.foreach_set("co", co)
                    for kp in fc.keyframe_points:
                        kp.interpolation = "LINEAR" if a != 1 else "CONSTANT"
                    fc.update()
        names.append(oname)
    return names
