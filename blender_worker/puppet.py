"""A drawn cut-out character on a stick figure's skeleton (the layered-art step after costume.py).

Each body part is a picture cut from a generated part sheet (scripts/cut_puppet.py). In Blender it is a flat
mesh cut to the part's own pixel mask, with the picture mapped on it, so no transparency is needed. Every
frame a part is pinned at its joint and turned with its bone; limbs turn to their bone's direction, the
torso, hips, head, hair and shoes by how far their bone has turned from the standing pose. The far arm and
leg use darker copies. Facing left mirrors every part. This is a look only: the motion is the figure's.
"""
import json
import math
import os

import bpy
import numpy as np

import motion

CELL = 3                                   # mesh cell size in sheet pixels
HEAD_K = 0.87                              # the side sheet's head is drawn ~15% bigger than the front's

# Side view, drawn facing right. N = near side, F = far side. sheet points are (x, y) pixels, y down.
#   file, anchor (sheet px), bone (joint a, joint b), mode, depth (bigger = further back), extra
SIDE = [
    ("upper_a_dark", (435, 448), ("F_shoulder", "F_elbow"), ("bone", (432.5, 616.5)), 12.0, {}),
    ("fore_dark", (610, 628), ("F_elbow", "F_wrist"), ("bone", (628, 785)), 11.8, {}),
    ("shoe_b_dark", (432, None), ("F_ankle", "F_toe"), ("rest", None), 11.4, {"sole": 1168}),
    ("shin_b_dark", (437.5, 897.5), ("F_knee", "F_ankle"), ("bone", (432, 1088)), 11.0, {}),
    ("thigh_b_dark", (432.5, 721.5), ("F_hip", "F_knee"), ("bone", (437.5, 897.5)), 10.5, {}),
    ("shoe_a", (165, None), ("N_ankle", "N_toe"), ("rest", None), 8.0, {"sole": 1171}),
    ("shin_a", (176, 884), ("N_knee", "N_ankle"), ("bone", (163, 1075)), 7.5, {}),
    ("thigh_a", (170.5, 707.5), ("N_hip", "N_knee"), ("bone", (176, 884)), 7.0, {}),
    ("hips", (170.5, 707.5), ("pelvis", "sh"), ("rest", None), 6.0, {}),
    ("torso", (150, 425), ("pelvis", "sh"), ("rest", None), 5.0, {"at": "sh"}),
    ("head", (168, 300), ("neck", "head_top"), ("rest", None), 4.0, {"k": HEAD_K}),
    ("hair_back", (168 + 330, 300 + 6), ("neck", "head_top"), ("rest", None), 3.5, {"k": HEAD_K}),
    ("hair_front", (168 + 555, 300 - 5), ("neck", "head_top"), ("rest", None), 3.0, {"k": HEAD_K}),
    ("upper_b", (612.5, 472.5), ("N_shoulder", "N_elbow"), ("bone", (609.5, 609.5)), 2.0, {}),
    ("fore", (610, 628), ("N_elbow", "N_wrist"), ("bone", (628, 785)), 1.5, {}),
]
ART_LEG = ((170.5, 707.5), (163, 1075))    # hip and ankle on the side sheet: sets the drawing's scale
STEP = 0.004                               # depth between layers


def _joint(pose, name, facing):
    """A skeleton point by part-spec name: N_/F_ = near/far side (by facing), sh = between shoulders."""
    if name == "sh":
        a, b = pose["l_shoulder"], pose["r_shoulder"]
        return ((a[0] + b[0]) / 2, (a[-1] + b[-1]) / 2)
    if name[:2] in ("N_", "F_"):
        far = "l" if facing == "right" else "r"
        side = far if name[0] == "F" else ("r" if far == "l" else "l")
        name = f"{side}_{name[2:]}"
    p = pose[name]
    return (p[0], p[-1])


def _mesh(name, png, origin, anchor, scale):
    """A flat mesh covering the part's opaque pixels (CELL-sized squares), UV-mapped to its picture,
    in metres around `anchor` (sheet px). Returns the object."""
    img = bpy.data.images.load(png, check_existing=True)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    alpha = px.reshape(h, w, 4)[::-1, :, 3].copy()          # rows top-down, like the sheet
    img.alpha_mode = "NONE"                                  # the mesh is the cut-out; colours bleed past it
    cy, cx = np.mgrid[0:h:CELL, 0:w:CELL]
    centre = alpha[np.minimum(cy + CELL // 2, h - 1), np.minimum(cx + CELL // 2, w - 1)] > 0.5
    cells = np.argwhere(centre)                              # (row, col) of filled cells
    gw = cx.shape[1] + 1
    corners = np.concatenate([cells, cells + [0, 1], cells + [1, 1], cells + [1, 0]])
    ids, inv = np.unique(corners[:, 0] * gw + corners[:, 1], return_inverse=True)
    n = len(cells)
    faces = inv.reshape(4, n).T
    rows, cols = ids // gw, ids % gw
    sx = np.minimum(cols * CELL, w)
    sy = np.minimum(rows * CELL, h)
    verts = np.stack([(origin[0] + sx - anchor[0]) * scale, np.zeros(len(ids)),
                      -(origin[1] + sy - anchor[1]) * scale], 1)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts.tolist(), [], faces.tolist())
    uv = me.uv_layers.new(name="uv")
    loop_v = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", loop_v)
    uvs = np.stack([sx[loop_v] / w, 1.0 - sy[loop_v] / h], 1).astype(np.float32)
    uv.data.foreach_set("uv", uvs.ravel())
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Linear"
    mat.node_tree.nodes.active = tex
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def _angle(v):
    return math.atan2(v[1], v[0])


# Front view: a joint chain from the torso (the skeleton is narrow from the front, the drawing is not):
# each part hangs from a point on its parent's drawing and turns with its bone; the lower shoe stays on
# the ground. image-left is her right side.
#   file, parent, attach (on the parent, sheet px, or a skeleton joint for the root),
#   anchor (on the part; "top" / "bottom" = its round ends), rotation, depth
FRONT = [
    ("torso", None, "sh", (448, 392), ("rest", ("pelvis", "sh")), 5.0),
    ("neck", "torso", (448, 310), (448, 300), ("same", "torso"), 5.4),
    ("head", "torso", (448, 280), (448, 280), ("rest", ("neck", "head_top")), 4.0),
    ("hair_back", "head", (448, 280), (723, 280), ("same", "head"), 9.0),
    ("hair_front", "head", (448, 280), (171, 274), ("same", "head"), 3.0),
]
for _s, _sh, _hip, _shoe in (("r", (388, 392), (402, 625), (340, 1095)), ("l", (508, 392), (494, 625), (557, 1095))):
    FRONT += [
        (f"upper_{_s}", "torso", _sh, "top", ("bone", (f"{_s}_shoulder", f"{_s}_elbow")), 5.7),
        (f"fore_{_s}", f"upper_{_s}", "bottom", "top", ("bone", (f"{_s}_elbow", f"{_s}_wrist")), 5.6),
        (f"hand_{_s}", f"fore_{_s}", "bottom", "top", ("same", f"fore_{_s}"), 5.5),
        (f"thigh_{_s}", "torso", _hip, "top", ("bone", (f"{_s}_hip", f"{_s}_knee")), 7.0),
        (f"shin_{_s}", f"thigh_{_s}", "bottom", "top", ("bone", (f"{_s}_knee", f"{_s}_ankle")), 7.3),
        (f"shoe_{_s}", f"shin_{_s}", "bottom", _shoe, ("rest", (f"{_s}_knee", f"{_s}_ankle")), 7.6),
    ]
SOLE = 1173                                # the front shoes' soles on the sheet
SQUASH = ("thigh_r", "thigh_l", "shin_r", "shin_l")   # shortened when they point at the camera (sitting)


def _key(o, fs, keys, fcurves):
    o.keyframe_insert("location", frame=fs[0])
    o.keyframe_insert("rotation_euler", index=1, frame=fs[0])
    o.keyframe_insert("scale", index=0, frame=fs[0])
    o.keyframe_insert("scale", index=2, frame=fs[0])
    curves = {(fc.data_path, fc.array_index): fc for fc in fcurves(o)}
    for (path, idx), vals, interp in ((("location", 0), keys["x"], "LINEAR"),
                                      (("location", 2), keys["z"], "LINEAR"),
                                      (("rotation_euler", 1), _unwrap(keys["rot"]), "LINEAR"),
                                      (("scale", 0), keys["sx"], "CONSTANT"),
                                      (("scale", 2), keys.get("sz") or [1.0] * len(fs), "LINEAR")):
        fc = curves[(path, idx)]
        fc.keyframe_points.add(len(fs) - 1)
        co = []
        for f, v in zip(fs, vals):
            co += [f, v]
        fc.keyframe_points.foreach_set("co", co)
        for kp in fc.keyframe_points:
            kp.interpolation = interp
        fc.update()


def _new(name, fig, view, file, info, anchor, scale, depth, parts_dir):
    base = file.replace("_dark", "")
    o = _mesh(f"{name}__{view}_{file}", os.path.join(parts_dir, view, f"{file}.png"), info[base]["origin"],
              anchor, scale)
    o["kind"] = "puppet"
    o["puppet_of"] = name
    o.location = (0.0, fig.y + (depth - 6) * STEP, 0.0)
    return o


def _view(fig, f):
    _, view, facing, _ = fig.local[f] if f in fig.local else (None, "front", "front", None)
    return view, facing


def dress(name, fig, frames, parts_dir, appear=None, fcurves=None):
    L = fig.L
    s = (motion.THIGH + motion.SHIN) * L / math.dist(*ART_LEG)      # metres per sheet pixel
    fs = sorted(frames)
    out = []

    # ---- side view: each part pinned at its own skeleton joint
    info = json.load(open(os.path.join(parts_dir, "side", "parts.json")))
    rest = motion.longer_arms(motion.rest_pose("side"))      # leg units, facing right (u forward, v up)
    rest_pts = {k: (u * L, v * L) for k, (u, v) in rest.items()}
    ankle_h = (rest["r_ankle"][1] - motion.ground(rest)) * L + fig.r
    for file, anchor, (ja, jb), (mode, art_b), depth, extra in SIDE:
        k = extra.get("k", 1.0)
        if anchor[1] is None:                                # shoes: the sole sits on the ground
            anchor = (anchor[0], extra["sole"] - ankle_h / (s * k))
        o = _new(name, fig, "side", file, info, anchor, s * k, depth, parts_dir)
        art_angle = _angle((art_b[0] - anchor[0], -(art_b[1] - anchor[1]))) if mode == "bone" else None
        ra, rb = _joint(rest_pts, ja, "right"), _joint(rest_pts, jb, "right")
        rest_angle = _angle((rb[0] - ra[0], rb[1] - ra[1]))
        keys = {"x": [], "z": [], "rot": [], "sx": []}
        for f in fs:
            pose = frames[f]
            view, facing = _view(fig, f)
            facing = facing if facing in ("left", "right") else "right"
            m = 1 if facing == "right" else -1
            a, b = _joint(pose, ja, facing), _joint(pose, jb, facing)
            at = _joint(pose, extra["at"], facing) if "at" in extra else a
            ref = art_angle if mode == "bone" else rest_angle
            theta = _angle((b[0] - a[0], b[1] - a[1])) - _angle((m * math.cos(ref), math.sin(ref)))
            hide = view != "side" or (appear and f < appear)  # side parts only while side-on
            keys["x"].append(at[0])
            keys["z"].append(at[1] - (100.0 if hide else 0.0))
            keys["rot"].append(-theta)                       # Blender's Y rotation turns the other way
            keys["sx"].append(float(m))
        _key(o, fs, keys, fcurves)
        out.append(o.name)

    # ---- front view: a chain of drawn parts from the torso
    info = json.load(open(os.path.join(parts_dir, "front", "parts.json")))
    rest = motion.longer_arms(motion.rest_pose("front"))
    rest_pts = {k: (u * L, v * L) for k, (u, v) in rest.items()}

    def art(file, which):
        if isinstance(which, str):
            return tuple(info[file]["ends"][0 if which == "top" else 1])
        return which
    objs, spec = {}, {}
    for file, parent, attach, anchor, rot, depth in FRONT:
        a = art(file, anchor)
        spec[file] = (parent, attach, a, rot)
        objs[file] = _new(name, fig, "front", file, info, a, s, depth, parts_dir)
    keys = {file: {"x": [], "z": [], "rot": [], "sx": [], "sz": []} for file in objs}
    for f in fs:
        pose = frames[f]
        view, _ = _view(fig, f)
        tf = {}                                              # part -> (at x, at z, theta, anchor, squash)

        def place(file, p):                                  # a sheet point on a placed part, in metres
            x, z, th, a, q = tf[file]
            dx, dz = (p[0] - a[0]) * s, -(p[1] - a[1]) * s * q
            return x + dx * math.cos(th) - dz * math.sin(th), z + dx * math.sin(th) + dz * math.cos(th)
        for file, (parent, attach, a, rot) in spec.items():
            if parent is None:
                at = _joint(pose, attach, "front")
            else:
                at = place(parent, art(parent, attach))
            q = 1.0
            if rot[0] == "same":
                theta = tf[rot[1]][2]
            else:
                ja, jb = rot[1]
                p0, p1 = _joint(pose, ja, "front"), _joint(pose, jb, "front")
                bone = _angle((p1[0] - p0[0], p1[1] - p0[1]))
                if rot[0] == "rest":
                    r0, r1 = _joint(rest_pts, ja, "front"), _joint(rest_pts, jb, "front")
                    theta = bone - _angle((r1[0] - r0[0], r1[1] - r0[1]))
                else:
                    b = art(file, "bottom")
                    theta = bone - _angle((b[0] - a[0], -(b[1] - a[1])))
                if file in SQUASH:                           # as short as the bone looks from the front
                    r0, r1 = _joint(rest_pts, ja, "front"), _joint(rest_pts, jb, "front")
                    q = max(0.3, min(1.1, math.dist(p0, p1) / math.dist(r0, r1)))
            tf[file] = (at[0], at[1], theta, a, q)
        # the lower shoe stays on the skeleton's ground line
        feet = min(pose[j][-1] for j in ("l_toe", "r_toe", "l_ankle", "r_ankle")) - fig.r
        soles = [place(f"shoe_{side}", (tf[f"shoe_{side}"][3][0], SOLE))[1] for side in "rl"]
        dz = feet - min(soles)
        hide = view == "side" or (appear and f < appear)
        for file, (x, z, th, _, q) in tf.items():
            keys[file]["x"].append(x)
            keys[file]["z"].append(z + dz - (100.0 if hide else 0.0))
            keys[file]["rot"].append(-th)
            keys[file]["sx"].append(1.0)
            keys[file]["sz"].append(q)
    for file, o in objs.items():
        _key(o, fs, keys[file], fcurves)
        out.append(o.name)
    return out


def _unwrap(angles):
    """No 359° → 1° jumps between frames (the rotation is interpolated)."""
    out = [angles[0]]
    for a in angles[1:]:
        while a - out[-1] > math.pi:
            a -= 2 * math.pi
        while a - out[-1] < -math.pi:
            a += 2 * math.pi
        out.append(a)
    return out
