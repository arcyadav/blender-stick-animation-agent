"""Tools that run inside Blender (bpy). Arguments arrive already validated (schema.py).

Conventions the agent sees (also in the tool descriptions):
- `location` = [x, y, z] where x, y is the object's centre and z is the height of its BOTTOM,
  so z = 0 means "standing on the ground". It may also be a placement: {"on_top_of": name}, …
- rotation in degrees; colours as names, "#rrggbb" or [r, g, b] in 0..1.
- The default camera looks from -y toward +y, so screen-left is -x and screen-right is +x.
"""
import math
import os
import time

import bmesh
import bpy
from mathutils import Vector


class ToolError(Exception):
    """A mistake the agent can fix (unknown name, impossible request). Sent back as the error text."""


OUT_DIR = "."          # set by worker.py
_render_count = 0

COLOURS = {
    "red": (0.8, 0.05, 0.05), "orange": (0.9, 0.35, 0.02), "yellow": (0.95, 0.8, 0.05),
    "green": (0.1, 0.6, 0.12), "blue": (0.05, 0.2, 0.8), "purple": (0.45, 0.1, 0.7),
    "pink": (0.95, 0.4, 0.6), "white": (0.9, 0.9, 0.9), "black": (0.02, 0.02, 0.02),
    "grey": (0.4, 0.4, 0.4), "brown": (0.35, 0.18, 0.07),
}
COLOURS["gray"] = COLOURS["grey"]

MATERIAL_PRESETS = {
    "matte":   {"Roughness": 0.9, "Metallic": 0.0},
    "plastic": {"Roughness": 0.35, "Metallic": 0.0},
    "metal":   {"Roughness": 0.25, "Metallic": 1.0},
    "glass":   {"Roughness": 0.0, "Metallic": 0.0, "Transmission Weight": 1.0},
    "glow":    {"Roughness": 0.5, "Metallic": 0.0, "Emission Strength": 3.0},
    "wood":    {"Roughness": 0.6, "Metallic": 0.0},
}

INTERNAL = "p5_internal"     # custom property on helper objects (camera target, ground is NOT internal)


# ---------------------------------------------------------------- helpers

def _obj(name):
    o = bpy.data.objects.get(name)
    if o is None or o.get(INTERNAL):
        names = ", ".join(sorted(x.name for x in _scene_objects())) or "none"
        raise ToolError(f"no object named '{name}'. Objects in the scene: {names}")
    return o


def _scene_objects():
    return [o for o in bpy.context.scene.objects if not o.get(INTERNAL)]


def _rgb(colour):
    if isinstance(colour, str):
        c = colour.strip().lower()
        if c in COLOURS:
            return COLOURS[c]
        if c.startswith("#") and len(c) == 7:
            return tuple(int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
        raise ToolError(f"unknown colour '{colour}'. Use one of {', '.join(k for k in COLOURS if k != 'gray')}, "
                        "'#rrggbb' or [r, g, b]")
    return tuple(float(v) for v in colour)


def colour_name(rgb):
    return min((k for k in COLOURS if k != "gray"),
               key=lambda k: sum((a - b) ** 2 for a, b in zip(COLOURS[k], rgb[:3])))


def _world_bounds(o):
    """(min, max) corners of the object's world-space bounding box at the current frame."""
    bpy.context.view_layer.update()
    if o.type == "MESH" and 0 < len(o.data.vertices) <= 20000:
        # exact for rotated shapes (a rolling ball's rotated box would poke into the floor)
        mw = o.matrix_world
        pts = [mw @ v.co for v in o.data.vertices]
    else:
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def _bottom_centre(o):
    lo, hi = _world_bounds(o)
    return Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))


def _support_top(o):
    """Height objects rest on: assets may carry their own (e.g. a table top), else the bbox top."""
    lo, hi = _world_bounds(o)
    return lo.z + o["top_z"] * o.scale.z if "top_z" in o else hi.z


SIDES = {"left": Vector((-1, 0, 0)), "right": Vector((1, 0, 0)),
         "front": Vector((0, -1, 0)), "back": Vector((0, 1, 0))}


def _resolve_location(o, loc):
    """Turn a location argument into the target bottom-centre point for object o."""
    if isinstance(loc, (list, tuple)):
        return Vector(loc)
    if "on_top_of" in loc:
        t = _obj(loc["on_top_of"])
        lo, hi = _world_bounds(t)
        dx, dy = loc.get("offset", [0, 0])
        return Vector(((lo.x + hi.x) / 2 + dx, (lo.y + hi.y) / 2 + dy, _support_top(t)))
    if "next_to" in loc or "in_front_of" in loc:
        key = "next_to" if "next_to" in loc else "in_front_of"
        t = _obj(loc[key])
        side = SIDES[loc.get("side", "right") if key == "next_to" else "front"]
        gap = loc.get("gap", 0.2) if key == "next_to" else loc.get("distance", 1.0)
        tlo, thi = _world_bounds(t)
        olo, ohi = _world_bounds(o)
        t_half = (thi - tlo) / 2
        o_half = (ohi - olo) / 2
        centre = (tlo + thi) / 2
        reach = abs(side.x) * (t_half.x + o_half.x) + abs(side.y) * (t_half.y + o_half.y) + gap
        p = centre + side * reach
        return Vector((p.x, p.y, 0.0))
    raise ToolError("location must be [x, y, z] or one of {on_top_of}, {next_to, side}, {in_front_of, distance}")


def _place(o, loc):
    """Move o so its bottom-centre lands on the resolved location (respects current rotation/scale)."""
    target = _resolve_location(o, loc)
    o.location += target - _bottom_centre(o)
    bpy.context.view_layer.update()


def _normalise(bm, size, keep_floor=False):
    """Centre the mesh on the origin and scale it so its largest extent is `size`."""
    xs = [v.co.x for v in bm.verts]; ys = [v.co.y for v in bm.verts]; zs = [v.co.z for v in bm.verts]
    c = Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2))
    ext = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) or 1.0
    for v in bm.verts:
        v.co = (v.co - c) * (size / ext)


def _torus(bm, major=0.375, minor=0.125, n=40, m=16):
    ring = []
    for i in range(n):
        a = 2 * math.pi * i / n
        ring.append([bm.verts.new(((major + minor * math.cos(b)) * math.cos(a),
                                   (major + minor * math.cos(b)) * math.sin(a),
                                   minor * math.sin(b)))
                     for b in (2 * math.pi * j / m for j in range(m))])
    for i in range(n):
        for j in range(m):
            bm.faces.new((ring[i][j], ring[(i + 1) % n][j], ring[(i + 1) % n][(j + 1) % m], ring[i][(j + 1) % m]))


def _make_mesh(name, kind, size):
    bm = bmesh.new()
    if kind == "cube":
        bmesh.ops.create_cube(bm, size=1.0)
    elif kind == "sphere":
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=0.5)
    elif kind == "cylinder":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=0.5, radius2=0.5, depth=1.0)
    elif kind == "cone":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=0.5, radius2=0.0, depth=1.0)
    elif kind == "plane":
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
    elif kind == "torus":
        _torus(bm)
    _normalise(bm, size)
    if kind in ("sphere", "torus"):
        for f in bm.faces:
            f.smooth = True
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def _material(o):
    if o.data is None or not hasattr(o.data, "materials"):
        raise ToolError(f"'{o.name}' can't have a material")
    if o.data.materials and o.data.materials[0]:
        return o.data.materials[0]
    m = bpy.data.materials.new(f"{o.name}_mat")
    m.use_nodes = True
    o.data.materials.append(m)
    return m


def _bsdf(m):
    return m.node_tree.nodes["Principled BSDF"]


def _apply_colour(m, rgb):
    rgba = (*rgb, 1.0)
    _bsdf(m).inputs["Base Color"].default_value = rgba
    m.diffuse_color = rgba                      # Workbench check renders use this one
    if m.get("preset") == "glow":
        _bsdf(m).inputs["Emission Color"].default_value = rgba


def _fcurves(id_data):
    ad = id_data.animation_data
    if not ad or not ad.action:
        return []
    act = ad.action
    try:
        return list(act.fcurves)              # legacy accessor (still present in 4.5)
    except AttributeError:
        out = []
        for layer in act.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    out.extend(bag.fcurves)
        return out


def _prop_fcurves(o, prop):
    if prop == "colour":
        m = _material(o)
        curves = _fcurves(m) + _fcurves(m.node_tree)
        return [fc for fc in curves if "default_value" in fc.data_path or fc.data_path == "diffuse_color"]
    path = {"location": "location", "rotation": "rotation_euler", "scale": "scale"}[prop]
    return [fc for fc in _fcurves(o) if fc.data_path == path]


def _r(v, n=2):
    return [round(x, n) for x in v]


# ---------------------------------------------------------------- tools

def scene_reset():
    """Empty scene with a ground plane, a default camera, day light, 1–72 at 24 fps (3 s)."""
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.actions):
        for block in list(coll):
            coll.remove(block)
    scn = bpy.context.scene
    scn.frame_start, scn.frame_end = 1, 72
    scn.render.fps = 24
    scn.frame_set(1)
    ground = bpy.data.objects.new("ground", _make_mesh("ground", "plane", 20.0))
    ground["kind"] = "ground"
    scn.collection.objects.link(ground)
    _apply_colour(_material(ground), (0.55, 0.55, 0.55))
    _bsdf(_material(ground)).inputs["Roughness"].default_value = 0.9

    target = bpy.data.objects.new("camera_target", None)
    target[INTERNAL] = True
    scn.collection.objects.link(target)
    cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    cam["kind"] = "camera"
    scn.collection.objects.link(cam)
    scn.camera = cam
    set_camera(location=[0, -8, 2.5], look_at=[0, 0, 0.8], focal_length=35)
    add_light(preset="day")
    return {"message": "empty scene: ground (20 m × 20 m at z = 0), camera at [0, -8, 2.5] looking at "
                       "[0, 0, 0.8], day light, frames 1–72 at 24 fps"}


def add_primitive(type, name, location=(0, 0, 0), size=1.0, colour=None, preset=None):
    if bpy.data.objects.get(name):
        raise ToolError(f"an object named '{name}' already exists; pick another name or use set_transform")
    o = bpy.data.objects.new(name, _make_mesh(name, type, size))
    o["kind"] = type
    bpy.context.scene.collection.objects.link(o)
    _place(o, location)
    set_material(name, colour=colour or "white", preset=preset or "plastic")
    return {"name": name, "bottom_centre": _r(_bottom_centre(o)), "size": _r(o.dimensions)}


# Props are built from primitives: one flat style with the stick figures, no downloads, and an exact
# support height (top_z, from the bottom) for things that hold other things.
# part = (shape, bottom-centre, size, material slot[, top radius ratio for cylinders])
WOOD, CARDBOARD, LEAF, BARK = (0.45, 0.27, 0.12), (0.5, 0.3, 0.15), (0.15, 0.5, 0.15), (0.3, 0.18, 0.08)
ASSETS = {
    "table": {"top_z": 0.75, "colours": [WOOD], "parts": [
        ("box", (0, 0, 0.7), (1.2, 0.8, 0.05), 0),
        *[("box", (x, y, 0), (0.06, 0.06, 0.7), 0) for x in (-0.55, 0.55) for y in (-0.35, 0.35)]]},
    "chair": {"top_z": 0.46, "colours": [WOOD], "parts": [
        ("box", (0, 0, 0.42), (0.45, 0.45, 0.04), 0),
        ("box", (0, 0.205, 0.46), (0.45, 0.04, 0.45), 0),
        *[("box", (x, y, 0), (0.04, 0.04, 0.42), 0) for x in (-0.2, 0.2) for y in (-0.2, 0.2)]]},
    "bench": {"top_z": 0.45, "colours": [WOOD], "parts": [
        ("box", (0, 0, 0.4), (1.5, 0.4, 0.05), 0),
        *[("box", (x, 0, 0), (0.06, 0.36, 0.4), 0) for x in (-0.65, 0.65)]]},
    "box": {"top_z": 0.5, "colours": [CARDBOARD], "parts": [("box", (0, 0, 0), (0.5, 0.5, 0.5), 0)]},
    "lamp": {"colours": [(0.95, 0.9, 0.75), (0.1, 0.1, 0.1)], "parts": [
        ("cyl", (0, 0, 0), (0.18, 0.18, 0.03), 1),
        ("cyl", (0, 0, 0.03), (0.03, 0.03, 0.27), 1),
        ("cyl", (0, 0, 0.28), (0.25, 0.25, 0.18), 0, 0.6)]},
    "tree": {"colours": [LEAF, BARK], "parts": [
        ("cyl", (0, 0, 0), (0.25, 0.25, 1.2), 1),
        ("sphere", (0, 0, 0.9), (1.4, 1.4, 1.8), 0)]},
}


def _asset_mesh(name, asset):
    from mathutils import Matrix
    bm = bmesh.new()
    for part in ASSETS[asset]["parts"]:
        shape, (x, y, z0), (sx, sy, sz), slot = part[:4]
        m = Matrix.Translation((x, y, z0 + sz / 2)) @ Matrix.Diagonal((sx, sy, sz, 1))
        before = set(bm.faces)
        if shape == "box":
            bmesh.ops.create_cube(bm, size=1.0, matrix=m)
        elif shape == "cyl":
            top = part[4] if len(part) > 4 else 1.0
            bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=0.5, radius2=0.5 * top,
                                  depth=1.0, matrix=m)
        else:
            bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=0.5, matrix=m)
        for f in set(bm.faces) - before:
            f.material_index = slot
            f.smooth = shape == "sphere"
    # origin at the bounding-box centre, like the primitives
    zs = [v.co.z for v in bm.verts]
    shift = Vector((0, 0, (min(zs) + max(zs)) / 2))
    for v in bm.verts:
        v.co -= shift
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def add_asset(asset, name, location=(0, 0, 0), scale=1.0, colour=None):
    if bpy.data.objects.get(name):
        raise ToolError(f"an object named '{name}' already exists; pick another name or use set_transform")
    spec = ASSETS[asset]
    o = bpy.data.objects.new(name, _asset_mesh(name, asset))
    o["kind"] = asset
    if "top_z" in spec:
        o["top_z"] = spec["top_z"]
    o.scale = [scale] * 3
    bpy.context.scene.collection.objects.link(o)
    for i, rgb in enumerate(spec["colours"]):
        m = bpy.data.materials.new(f"{name}_mat{i}")
        m.use_nodes = True
        m["preset"] = "matte"
        _bsdf(m).inputs["Roughness"].default_value = 0.8
        _apply_colour(m, rgb)
        o.data.materials.append(m)
    if colour:
        _apply_colour(o.data.materials[0], _rgb(colour))
    _place(o, location)
    return {"name": name, "bottom_centre": _r(_bottom_centre(o)), "size": _r(o.dimensions),
            **({"top_height": round(_support_top(o), 2)} if "top_z" in spec else {})}


def set_transform(name, location=None, rotation=None, scale=None):
    o = _obj(name)
    standing = _bottom_centre(o)
    if rotation is not None:
        o.rotation_euler = [math.radians(a) for a in rotation]
    if scale is not None:
        o.scale = [scale] * 3 if isinstance(scale, (int, float)) else scale
    # without a new location, keep the object standing where it was
    _place(o, location if location is not None else list(standing))
    return {"name": name, "bottom_centre": _r(_bottom_centre(o)), "size": _r(o.dimensions),
            "rotation": _r([math.degrees(a) for a in o.rotation_euler], 1)}


def set_material(name, colour="white", preset="plastic"):
    o = _obj(name)
    m = _material(o)
    m["preset"] = preset
    b = _bsdf(m)
    b.inputs["Transmission Weight"].default_value = 0.0
    b.inputs["Emission Strength"].default_value = 0.0
    for k, v in MATERIAL_PRESETS[preset].items():
        b.inputs[k].default_value = v
    if preset == "wood" and colour == "white":
        colour = "brown"
    _apply_colour(m, _rgb(colour))
    return {"name": name, "colour": colour_name(_rgb(colour)), "preset": preset}


def add_light(preset="day"):
    for o in [o for o in bpy.data.objects if o.type == "LIGHT"]:
        bpy.data.objects.remove(o, do_unlink=True)
    scn = bpy.context.scene
    world = scn.world or bpy.data.worlds.new("world")
    scn.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]

    def light(name, kind, energy, colour, location, aim=(0, 0, 0.5)):
        ld = bpy.data.lights.new(name, kind)
        ld.energy = energy
        ld.color = colour
        o = bpy.data.objects.new(name, ld)
        o[INTERNAL] = True
        o.location = location
        o.rotation_euler = (Vector(aim) - Vector(location)).to_track_quat("-Z", "Y").to_euler()
        scn.collection.objects.link(o)
        return o

    if preset == "day":
        light("sun", "SUN", 4.0, (1.0, 0.97, 0.92), (4, -3, 8))
        world_col, strength = (0.55, 0.65, 0.8), 0.8
    elif preset == "studio":
        light("key", "AREA", 400, (1, 1, 1), (3, -3, 4))
        light("fill", "AREA", 150, (1, 1, 1), (-4, -2, 2.5))
        light("rim", "AREA", 250, (1, 1, 1), (0, 4, 3))
        world_col, strength = (0.3, 0.3, 0.3), 0.5
    elif preset == "sunset":
        light("sun", "SUN", 2.5, (1.0, 0.55, 0.3), (-8, 2, 1.5))
        world_col, strength = (0.9, 0.5, 0.35), 0.5
    else:  # night
        light("moon", "SUN", 0.3, (0.6, 0.7, 1.0), (3, 2, 8))
        light("lamp_light", "POINT", 150, (1.0, 0.8, 0.55), (2, -2, 3))
        world_col, strength = (0.02, 0.03, 0.08), 1.0
    bg.inputs["Color"].default_value = (*world_col, 1)
    bg.inputs["Strength"].default_value = strength
    scn["light_preset"] = preset
    return {"preset": preset}


def set_camera(location=None, look_at=None, focal_length=None):
    cam = bpy.context.scene.camera
    target = bpy.data.objects["camera_target"]
    if location is not None:
        # a fixed placement replaces earlier camera moves
        cam.animation_data_clear()
        target.animation_data_clear()
        cam.location = location
    if focal_length is not None:
        cam.data.lens = focal_length
    if look_at is not None:
        cam.constraints.clear()
        c = cam.constraints.new("TRACK_TO")
        c.track_axis, c.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
        if isinstance(look_at, str):
            c.target = _obj(look_at)
            cam["look_at"] = look_at
        else:
            target.location = look_at
            c.target = target
            cam["look_at"] = list(look_at)
    return {"location": _r(cam.location), "look_at": _look_at(cam), "focal_length": cam.data.lens}


def _look_at(cam):
    v = cam.get("look_at")
    return v if isinstance(v, str) else _r(v) if v is not None else None


def _smooth(t):
    return t * t * (3 - 2 * t)


def _point(target):
    if isinstance(target, str):
        lo, hi = _world_bounds(_obj(target))
        return (lo + hi) / 2
    return Vector(target)


def _key_linear(id_data, path):
    for fc in _fcurves(id_data):
        if fc.data_path == path:
            for k in fc.keyframe_points:
                k.interpolation = "LINEAR"


def camera_move(kind, target=None, start_frame=None, end_frame=None, degrees=90, amount=None):
    """orbit / dolly_in / dolly_out / follow / pan, eased in and out between start and end frame."""
    scn = bpy.context.scene
    cam = scn.camera
    s = scn.frame_start if start_frame is None else start_frame
    e = scn.frame_end if end_frame is None else end_frame
    if e <= s:
        raise ToolError(f"end_frame ({e}) must be after start_frame ({s})")
    if target is None:
        target = cam.get("look_at")
        target = target if isinstance(target, str) else list(target)
    if kind == "follow" and not isinstance(target, str):
        raise ToolError("follow needs the name of the object to follow as target")
    scn.frame_set(s)
    start = cam.location.copy()

    if kind == "pan":
        old = cam.get("look_at")
        p0 = _point(old if isinstance(old, str) else list(old))
        set_camera(look_at=list(p0))
        tgt = bpy.data.objects["camera_target"]
        for f, p in ((s, p0), (e, _point(target))):
            tgt.location = p
            tgt.keyframe_insert("location", frame=f)
        cam["look_at"] = target if isinstance(target, str) else list(target)
    else:
        set_camera(look_at=target)
        if kind == "orbit":
            c = _point(target)
            rel = start - c
            r, a0 = math.hypot(rel.x, rel.y), math.atan2(rel.y, rel.x)
            for f in range(s, e + 1):
                a = a0 + math.radians(degrees) * _smooth((f - s) / (e - s))
                cam.location = (c.x + r * math.cos(a), c.y + r * math.sin(a), start.z)
                cam.keyframe_insert("location", frame=f)
            _key_linear(cam, "location")
        elif kind in ("dolly_in", "dolly_out"):
            c = _point(target)
            factor = amount or (0.6 if kind == "dolly_in" else 1.5)
            for f, p in ((s, start), (e, c + (start - c) * factor)):
                cam.location = p
                cam.keyframe_insert("location", frame=f)
        elif kind == "follow":
            o = _obj(target)
            offset = start - _bottom_centre(o)
            for f in range(s, e + 1):
                scn.frame_set(f)
                b = _bottom_centre(o)
                cam.location = (b.x + offset.x, b.y + offset.y, start.z)
                cam.keyframe_insert("location", frame=f)
            _key_linear(cam, "location")
    scn.frame_set(s)
    return {"kind": kind, "target": target if isinstance(target, str) else _r(target),
            "frames": [s, e], "camera_start": _r(start)}


def keyframe(name, property, frame, value):
    o = _obj(name)
    scn = bpy.context.scene
    scn.frame_set(frame)
    if property == "location":
        _place(o, value)
        o.keyframe_insert("location", frame=frame)
    elif property == "rotation":
        o.rotation_euler = [math.radians(a) for a in value]
        o.keyframe_insert("rotation_euler", frame=frame)
    elif property == "scale":
        o.scale = [value] * 3 if isinstance(value, (int, float)) else value
        o.keyframe_insert("scale", frame=frame)
    elif property == "colour":
        m = _material(o)
        _apply_colour(m, _rgb(value))
        _bsdf(m).inputs["Base Color"].keyframe_insert("default_value", frame=frame)
        m.keyframe_insert("diffuse_color", frame=frame)
    if frame > scn.frame_end:
        scn.frame_end = frame
    return {"name": name, "property": property, "frame": frame,
            "keys": sorted({int(k.co.x) for fc in _prop_fcurves(o, property) for k in fc.keyframe_points})}


EASINGS = {
    "linear": ("LINEAR", None), "constant": ("CONSTANT", None), "ease_in_out": ("BEZIER", None),
    "ease_in": ("QUAD", "EASE_IN"), "ease_out": ("QUAD", "EASE_OUT"),
    "bounce": ("BOUNCE", "EASE_OUT"), "elastic": ("ELASTIC", "EASE_OUT"),
}


def set_easing(name, property, interpolation, from_frame=None, to_frame=None):
    """'gravity': each falling segment speeds up (ease in), each rising one slows down (ease out)."""
    o = _obj(name)
    curves = _prop_fcurves(o, property)
    if not curves:
        raise ToolError(f"'{name}' has no {property} keyframes yet; add them with keyframe first")
    n = 0
    for fc in curves:
        pts = list(fc.keyframe_points)
        for i, k in enumerate(pts):
            if from_frame is not None and k.co.x < from_frame or to_frame is not None and k.co.x >= to_frame:
                continue
            if interpolation == "gravity" and fc.array_index != 2:
                k.interpolation = "LINEAR"          # sideways travel keeps a steady speed
            elif interpolation == "gravity":
                nxt = pts[i + 1] if i + 1 < len(pts) else None
                falling = nxt is not None and nxt.co.y < k.co.y
                k.interpolation, k.easing = "QUAD", ("EASE_IN" if falling else "EASE_OUT")
            else:
                interp, easing = EASINGS[interpolation]
                k.interpolation = interp
                if easing:
                    k.easing = easing
                if interp == "BEZIER":
                    k.handle_left_type = k.handle_right_type = "AUTO_CLAMPED"
            n += 1
        fc.update()
    return {"name": name, "property": property, "interpolation": interpolation, "keys_changed": n}


def set_frames(start, end, fps=24):
    scn = bpy.context.scene
    scn.frame_start, scn.frame_end, scn.render.fps = start, end, fps
    return {"start": start, "end": end, "fps": fps, "seconds": round((end - start + 1) / fps, 2)}


def _anim_summary(o):
    out = {}
    for prop in ("location", "rotation", "scale", "colour"):
        try:
            curves = _prop_fcurves(o, prop)
        except ToolError:
            curves = []
        keys = sorted({int(k.co.x) for fc in curves for k in fc.keyframe_points})
        if keys:
            out[prop] = keys
    return out


def scene_state():
    scn = bpy.context.scene
    cur = scn.frame_current
    scn.frame_set(scn.frame_start)
    objs = []
    for o in _scene_objects():
        if o.type != "MESH":
            continue
        entry = {"name": o.name, "kind": o.get("kind", "mesh")}
        if o.get("kind") != "ground":
            m = o.data.materials[0] if o.data.materials else None
            if m:
                entry["colour"] = colour_name(m.diffuse_color)
                entry["preset"] = m.get("preset")
            entry["bottom_centre"] = _r(_bottom_centre(o))
            entry["size"] = _r(o.dimensions)
            if any(abs(a) > 1e-4 for a in o.rotation_euler):
                entry["rotation"] = _r([math.degrees(a) for a in o.rotation_euler], 1)
            anim = _anim_summary(o)
            if anim:
                entry["keyframes"] = anim
        objs.append(entry)
    cam = scn.camera
    state = {
        "frames": {"start": scn.frame_start, "end": scn.frame_end, "fps": scn.render.fps,
                   "seconds": round((scn.frame_end - scn.frame_start + 1) / scn.render.fps, 2)},
        "objects": objs,
        "camera": {"location": _r(cam.location), "look_at": _look_at(cam), "focal_length": cam.data.lens,
                   **({"moves_between_frames": [min(keys), max(keys)]}
                      if (keys := [int(k.co.x) for fc in _fcurves(cam) for k in fc.keyframe_points]) else {})},
        "light": scn.get("light_preset"),
        "note": "bottom_centre = [x, y, height of the object's bottom] at the first frame",
    }
    scn.frame_set(cur)
    return state


def _render_settings(engine, w, h):
    r = bpy.context.scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
    if engine == "workbench":
        r.engine = "BLENDER_WORKBENCH"
        sh = bpy.context.scene.display.shading
        sh.light, sh.color_type, sh.show_shadows = "STUDIO", "MATERIAL", True
    else:
        ids = {e.identifier for e in r.bl_rna.properties["engine"].enum_items}
        r.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in ids else "BLENDER_EEVEE"
        bpy.context.scene.eevee.taa_render_samples = 16


def render_check(frames):
    global _render_count
    _render_count += 1
    scn = bpy.context.scene
    _render_settings("workbench", 960, 540)
    scn.render.image_settings.file_format = "PNG"
    paths = []
    for f in frames:
        scn.frame_set(f)
        scn.render.filepath = os.path.join(OUT_DIR, f"check{_render_count:02d}_f{f:04d}.png")
        bpy.ops.render.render(write_still=True)
        paths.append(scn.render.filepath)
    return {"images": paths}


def render_final(engine="eevee", filename="final.mp4"):
    scn = bpy.context.scene
    _render_settings(engine, 1280, 720)
    scn.render.image_settings.file_format = "FFMPEG"
    scn.render.ffmpeg.format, scn.render.ffmpeg.codec = "MPEG4", "H264"
    scn.render.ffmpeg.constant_rate_factor = "HIGH"
    scn.render.filepath = os.path.join(OUT_DIR, filename)
    scn.render.use_file_extension = False
    t = time.time()
    bpy.ops.render.render(animation=True)
    return {"video": scn.render.filepath, "engine": scn.render.engine, "seconds": round(time.time() - t, 1)}


def _visible_fraction(o, cam_pos, deps):
    """Share of up to 12 points on o's camera-facing faces that the camera can see (nothing else in
    between). Points are face centres nudged 2 mm outward, so faces resting on the ground or a
    table don't count as hidden, and sparse shapes (a table's legs) are sampled where they are.
    None if o has no size or no face toward the camera."""
    lo, hi = _world_bounds(o)
    if (hi - lo).length < 1e-3:
        return None
    mw = o.matrix_world
    nm = mw.to_3x3().inverted_safe().transposed()
    pts = []
    for poly in o.data.polygons:
        c = mw @ poly.center
        n = (nm @ poly.normal).normalized()
        if n.z > -0.5 and n.dot(cam_pos - c) > 0:
            pts.append(c + n * 0.002)
    if not pts:
        return None
    pts = pts[::max(1, len(pts) // 12)][:12]
    seen = 0
    for p in pts:
        d = p - cam_pos
        ok, _loc, _n, _i, hit, _m = bpy.context.scene.ray_cast(deps, cam_pos, d.normalized(),
                                                               distance=d.length - 0.001)
        seen += (not ok) or (hit is not None and hit.original.name == o.name)
    return seen / len(pts)


def _world_bvh(o, deps):
    """BVH of o in world space, shrunk 1 cm per side so resting contact doesn't count as a collision."""
    from mathutils.bvhtree import BVHTree
    eo = o.evaluated_get(deps)
    me = eo.to_mesh()
    lo, hi = _world_bounds(o)
    c, d = (lo + hi) / 2, hi - lo
    s = Vector([max(0.0, 1 - 0.02 / x) if x > 0 else 1.0 for x in d])
    verts = []
    for v in me.vertices:
        p = o.matrix_world @ v.co - c
        verts.append(c + Vector((p.x * s.x, p.y * s.y, p.z * s.z)))
    polys = [tuple(p.vertices) for p in me.polygons]
    eo.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys)


def sample_scene(vis_step=6):
    """Per-frame data the checker needs (checks/ evaluates it outside Blender)."""
    from bpy_extras.object_utils import world_to_camera_view
    scn = bpy.context.scene
    cam = scn.camera
    objs = [o for o in _scene_objects() if o.type == "MESH" and o.get("kind") != "ground"]
    out = {"start": scn.frame_start, "end": scn.frame_end, "fps": scn.render.fps,
           "light": scn.get("light_preset"), "frames": [], "camera": [], "collisions": [],
           "objects": {o.name: {"kind": o.get("kind", "mesh"),
                                "top_z": o.get("top_z"), "frames": []} for o in objs}}
    for f in range(scn.frame_start, scn.frame_end + 1):
        scn.frame_set(f)
        deps = bpy.context.evaluated_depsgraph_get()
        key = (f - scn.frame_start) % vis_step == 0 or f == scn.frame_end
        out["frames"].append(f)
        q = cam.matrix_world.to_quaternion()
        cam_pos = cam.matrix_world.translation.copy()
        out["camera"].append({"loc": _r(cam_pos, 3), "fwd": _r(q @ Vector((0, 0, -1)), 3),
                              "right": _r(q @ Vector((1, 0, 0)), 3)})
        for o in objs:
            lo, hi = _world_bounds(o)
            sc = [world_to_camera_view(scn, cam, o.matrix_world @ Vector(c)) for c in o.bound_box]
            m = o.data.materials[0] if o.data.materials else None
            e = {"lo": _r(lo, 3), "hi": _r(hi, 3),
                 "rot": _r([math.degrees(a) for a in o.rotation_euler], 1), "scale": _r(o.scale, 3),
                 "colour": _r(m.diffuse_color[:3], 3) if m else None,
                 "screen": _r([min(p.x for p in sc), min(p.y for p in sc), max(p.x for p in sc),
                               max(p.y for p in sc)], 3),
                 "in_front": all(p.z > 0 for p in sc)}
            if key:
                e["visible"] = _visible_fraction(o, cam_pos, deps)
            out["objects"][o.name]["frames"].append(e)
        if key:
            boxes = {o.name: _world_bounds(o) for o in objs}
            pairs = [(a, b) for i, a in enumerate(objs) for b in objs[i + 1:]
                     if all(boxes[a.name][0][k] < boxes[b.name][1][k] - 0.01 and
                            boxes[b.name][0][k] < boxes[a.name][1][k] - 0.01 for k in range(3))]
            if pairs:
                bvh = {}
                for a, b in pairs:
                    for o in (a, b):
                        if o.name not in bvh:
                            bvh[o.name] = _world_bvh(o, deps)
                    if bvh[a.name].overlap(bvh[b.name]):
                        out["collisions"].append([a.name, b.name, f])
    scn.frame_set(scn.frame_start)
    return out


def set_output(subdir=""):
    """Internal (not offered to the agent): where renders and .blend files of the next task go."""
    global OUT_DIR, _render_count, _BASE_OUT
    _BASE_OUT = globals().get("_BASE_OUT") or OUT_DIR
    OUT_DIR = os.path.join(_BASE_OUT, subdir)
    os.makedirs(OUT_DIR, exist_ok=True)
    _render_count = 0
    return {"out": OUT_DIR}


def save_blend(filename="scene.blend"):
    path = os.path.join(OUT_DIR, filename)
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    return {"blend": path}


TOOLS = {f.__name__: f for f in (
    scene_reset, scene_state, add_primitive, add_asset, set_transform, set_material, add_light, set_camera,
    camera_move, keyframe, set_easing, set_frames, render_check, render_final, sample_scene, set_output,
    save_blend)}
