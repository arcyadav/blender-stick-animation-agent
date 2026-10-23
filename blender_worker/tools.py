"""Tools that run inside Blender (bpy). Arguments arrive already validated (schema.py).

The world is 2D, seen from the side like a sheet of paper (flat colours, white background, black
ground line, orthographic camera). Conventions the agent sees (also in the tool descriptions):
- `location` = [x, z]: x is left/right (screen-left is negative), z is the height of the object's
  BOTTOM, so z = 0 means "standing on the ground". [x, y, z] is accepted too (y = depth). It may also
  be a placement: {"on_top_of": name} or {"next_to": name, "side": "left|right", "gap": m}.
- depth is only a `layer`: "back", "middle" (default) or "front"; front things are drawn over back
  things and nothing in different layers can collide.
- `rotation` = degrees in the picture plane, positive = clockwise on screen ([x, y, z] also accepted).
- colours as names, "#rrggbb" or [r, g, b] in 0..1.
"""
import copy
import json
import math
import os
import time

import bmesh
import bpy
from mathutils import Matrix, Vector

import motion


class ToolError(Exception):
    """A mistake the agent can fix (unknown name, impossible request). Sent back as the error text."""


OUT_DIR = "."          # set by worker.py
_render_count = 0
FIGURES = {}           # name → motion.Figure (cleared by scene_reset)

COLOURS = {
    "red": (0.8, 0.05, 0.05), "orange": (0.9, 0.35, 0.02), "yellow": (0.95, 0.8, 0.05),
    "green": (0.1, 0.6, 0.12), "blue": (0.05, 0.2, 0.8), "purple": (0.45, 0.1, 0.7),
    "pink": (0.95, 0.4, 0.6), "white": (0.9, 0.9, 0.9), "black": (0.02, 0.02, 0.02),
    "grey": (0.4, 0.4, 0.4), "brown": (0.35, 0.18, 0.07),
}
COLOURS["gray"] = COLOURS["grey"]
MATERIAL_PRESETS = ["matte", "plastic", "metal", "glass", "glow", "wood"]   # kept for the agent; flat look
LAYERS = {"back": 1.0, "middle": 0.0, "front": -1.0}
BACKGROUNDS = {"day": (1.0, 1.0, 1.0), "studio": (0.93, 0.93, 0.93), "sunset": (1.0, 0.86, 0.72),
               "night": (0.12, 0.14, 0.26)}
CAM_Y = -30.0
ASPECT = 16 / 9

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


def _things():
    """Objects the checks look at: meshes and stick figures, not the ground or the camera."""
    return [o for o in _scene_objects() if o.type in ("MESH", "CURVE") and o.get("kind") != "ground"]


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


def _points(o):
    """World-space vertices of o as drawn at the current frame (curves and figures evaluated)."""
    if o.type == "MESH" and 0 < len(o.data.vertices) <= 20000:
        mw = o.matrix_world
        return [mw @ v.co for v in o.data.vertices]
    if o.type == "CURVE":
        deps = bpy.context.evaluated_depsgraph_get()
        eo = o.evaluated_get(deps)
        me = eo.to_mesh()
        mw = eo.matrix_world
        pts = [mw @ v.co for v in me.vertices]
        eo.to_mesh_clear()
        if pts:
            return pts
    return [o.matrix_world @ Vector(c) for c in o.bound_box]


def _world_bounds(o):
    """(min, max) corners of the object's world-space bounding box at the current frame."""
    bpy.context.view_layer.update()
    # exact vertices: a rolling ball's rotated box would poke into the floor
    pts = _points(o)
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


def _xyz(loc, y):
    """[x, z] → (x, y, z) with the given depth; [x, y, z] passes through."""
    return Vector((loc[0], y, loc[1])) if len(loc) == 2 else Vector(loc)


def _resolve_location(o, loc, y=0.0):
    """Turn a location argument into the target bottom-centre point for object o."""
    if isinstance(loc, (list, tuple)):
        return _xyz(loc, y)
    if "on_top_of" in loc:
        t = _obj(loc["on_top_of"])
        if t.get("kind") == "figure":
            raise ToolError("things can't be put on a stick figure")
        lo, hi = _world_bounds(t)
        off = loc.get("offset", [0])
        return Vector(((lo.x + hi.x) / 2 + off[0], (lo.y + hi.y) / 2, _support_top(t)))
    if "next_to" in loc:
        t = _obj(loc["next_to"])
        side = -1 if loc.get("side", "right") == "left" else 1
        gap = loc.get("gap", 0.2)
        tlo, thi = _world_bounds(t)
        olo, ohi = _world_bounds(o)
        half = (ohi.x - olo.x) / 2
        x = (thi.x + gap + half) if side > 0 else (tlo.x - gap - half)
        return Vector((x, (tlo.y + thi.y) / 2, 0.0))
    raise ToolError("location must be [x, z] or one of {on_top_of}, {next_to, side}")


def _place(o, loc, layer=None):
    """Move o so its bottom-centre lands on the resolved location (respects current rotation/scale)."""
    y = LAYERS[layer] if layer else _bottom_centre(o).y
    target = _resolve_location(o, loc, y)
    if layer:
        target.y = LAYERS[layer]
    o.location += target - _bottom_centre(o)
    bpy.context.view_layer.update()


def _normalise(bm, size):
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
        bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=0.5)
    elif kind == "cylinder":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=0.5, radius2=0.5, depth=1.0)
    elif kind == "cone":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=0.5, radius2=0.0, depth=1.0)
    elif kind == "plane":
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
    elif kind == "torus":
        _torus(bm)
    if kind in ("plane", "torus"):
        # flat shapes face the camera in a side-view world (a panel, a ring)
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "X"))
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
    o.data.materials.append(m)
    return m


def _apply_colour(m, rgb):
    m.diffuse_color = (*rgb, 1.0)          # the flat renderer draws this colour


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
        return [fc for fc in _fcurves(_material(o)) if fc.data_path == "diffuse_color"]
    path = {"location": "location", "rotation": "rotation_euler", "scale": "scale"}[prop]
    return [fc for fc in _fcurves(o) if fc.data_path == path]


def _r(v, n=2):
    return [round(x, n) for x in v]


def _rotation(value):
    """A number = degrees clockwise on screen (about the depth axis); [x, y, z] = Euler degrees."""
    if isinstance(value, (int, float)):
        return [0.0, math.radians(value), 0.0]
    return [math.radians(a) for a in value]


def _no_figure(o, what):
    if o.get("kind") == "figure":
        raise ToolError(f"'{o.name}' is a stick figure: {what}")


def _layer_name(y):
    return min(LAYERS, key=lambda k: abs(LAYERS[k] - y))


# ---------------------------------------------------------------- scene

def scene_reset():
    """Empty 2D scene: ground line, default camera, white background, frames 1–72 at 24 fps (3 s)."""
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.actions):
        for block in list(coll):
            coll.remove(block)
    FIGURES.clear()
    scn = bpy.context.scene
    scn.frame_start, scn.frame_end = 1, 72
    scn.render.fps = 24
    scn.frame_set(1)
    # the ground: a thin black slab whose top is z = 0, seen edge-on as the ground line
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((0, 0, -0.015)) @ Matrix.Diagonal((80, 12, 0.03, 1)))
    me = bpy.data.meshes.new("ground")
    bm.to_mesh(me)
    bm.free()
    ground = bpy.data.objects.new("ground", me)
    ground["kind"] = "ground"
    scn.collection.objects.link(ground)
    _apply_colour(_material(ground), (0.0, 0.0, 0.0))

    target = bpy.data.objects.new("camera_target", None)
    target[INTERNAL] = True
    scn.collection.objects.link(target)
    cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    cam["kind"] = "camera"
    cam.data.type = "ORTHO"
    cam.data.clip_end = 100
    cam.rotation_euler = (math.pi / 2, 0, 0)       # looks along +y, up is +z
    scn.collection.objects.link(cam)
    scn.camera = cam
    set_camera(look_at=[0, 1.6], width=8)
    add_light(preset="day")
    _flat_look()
    return {"message": "empty 2D scene: ground line at z = 0, camera centred on [0, 1.6] showing 8 m across, "
                       "white background, frames 1–72 at 24 fps"}


def _flat_look():
    scn = bpy.context.scene
    scn.render.engine = "BLENDER_WORKBENCH"
    sh = scn.display.shading
    sh.light, sh.color_type = "FLAT", "MATERIAL"
    sh.show_shadows = sh.show_cavity = sh.show_specular_highlight = False
    sh.show_object_outline = True
    sh.object_outline_color = (0.0, 0.0, 0.0)
    scn.display.render_aa = "16"
    scn.view_settings.view_transform = "Standard"
    scn.view_settings.look = "None"


def _default_name(base):
    """A free name: 'table', then 'table2', … (small models often leave the name out)."""
    name, k = base, 1
    while bpy.data.objects.get(name):
        k += 1
        name = f"{base}{k}"
    return name


def add_primitive(type, name=None, location=(0, 0), size=1.0, colour=None, preset=None, layer=None):
    name = name or _default_name({"sphere": "ball"}.get(type, type))
    if bpy.data.objects.get(name):
        raise ToolError(f"an object named '{name}' already exists; pick another name or use set_transform")
    o = bpy.data.objects.new(name, _make_mesh(name, type, size))
    o["kind"] = type
    bpy.context.scene.collection.objects.link(o)
    _place(o, location, layer)
    # default grey: white would vanish on the white background
    set_material(name, colour=colour or "grey", preset=preset or "plastic")
    return {"name": name, "bottom_centre": _r(_bottom_centre(o)), "size": _r(o.dimensions),
            "layer": _layer_name(o.location.y)}


# Props are built from primitives in profile (the camera sees their side), with an exact support
# height (top_z, from the bottom) for things that hold other things.
# part = (shape, bottom-centre, size, material slot[, top radius ratio for cylinders])
WOOD, CARDBOARD, LEAF, BARK = (0.45, 0.27, 0.12), (0.5, 0.3, 0.15), (0.15, 0.5, 0.15), (0.3, 0.18, 0.08)
ASSETS = {
    "table": {"top_z": 0.75, "colours": [WOOD], "parts": [
        ("box", (0, 0, 0.7), (1.2, 0.8, 0.05), 0),
        *[("box", (x, y, 0), (0.06, 0.06, 0.7), 0) for x in (-0.55, 0.55) for y in (-0.35, 0.35)]]},
    # profile: the back is on the left, so the chair faces right (facing="left" mirrors it)
    "chair": {"top_z": 0.46, "colours": [WOOD], "parts": [
        ("box", (0, 0, 0.42), (0.45, 0.45, 0.04), 0),
        ("box", (-0.205, 0, 0.46), (0.04, 0.45, 0.5), 0),
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
            bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=0.5, matrix=m)
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


def add_asset(asset, name=None, location=(0, 0), scale=1.0, colour=None, layer=None, facing=None):
    name = name or _default_name(asset)
    if bpy.data.objects.get(name):
        raise ToolError(f"an object named '{name}' already exists; pick another name or use set_transform")
    spec = ASSETS[asset]
    o = bpy.data.objects.new(name, _asset_mesh(name, asset))
    o["kind"] = asset
    if "top_z" in spec:
        o["top_z"] = spec["top_z"]
    o.scale = [scale] * 3
    if facing == "left":
        o.rotation_euler = (0, 0, math.pi)
    bpy.context.scene.collection.objects.link(o)
    for i, rgb in enumerate(spec["colours"]):
        m = bpy.data.materials.new(f"{name}_mat{i}")
        m["preset"] = "matte"
        _apply_colour(m, rgb)
        o.data.materials.append(m)
    if colour:
        _apply_colour(o.data.materials[0], _rgb(colour))
    _place(o, location, layer)
    return {"name": name, "bottom_centre": _r(_bottom_centre(o)), "size": _r(o.dimensions),
            "layer": _layer_name(o.location.y),
            **({"top_height": round(_support_top(o), 2)} if "top_z" in spec else {})}


def set_transform(name, location=None, rotation=None, scale=None, layer=None):
    o = _obj(name)
    _no_figure(o, "place it with add_stick_figure and move it with play_action")
    standing = _bottom_centre(o)
    if rotation is not None:
        o.rotation_euler = _rotation(rotation)
    if scale is not None:
        o.scale = [scale] * 3 if isinstance(scale, (int, float)) else scale
    # without a new location, keep the object standing where it was
    _place(o, location if location is not None else list(standing), layer)
    return {"name": name, "bottom_centre": _r(_bottom_centre(o)), "size": _r(o.dimensions),
            "rotation": _r([math.degrees(a) for a in o.rotation_euler], 1), "layer": _layer_name(o.location.y)}


def set_material(name, colour="white", preset="plastic"):
    o = _obj(name)
    if o.get("kind") == "figure":
        _figure_colour(o, _rgb(colour))
        return {"name": name, "colour": colour_name(_rgb(colour))}
    m = _material(o)
    m["preset"] = preset
    if preset == "wood" and colour == "white":
        colour = "brown"
    _apply_colour(m, _rgb(colour))
    return {"name": name, "colour": colour_name(_rgb(colour)), "preset": preset}


def add_light(preset="day"):
    """In the flat 2D look the 'light' is the background colour: day white, sunset peach, night blue."""
    scn = bpy.context.scene
    world = scn.world or bpy.data.worlds.new("world")
    scn.world = world
    world.color = BACKGROUNDS[preset]
    scn["light_preset"] = preset
    return {"preset": preset, "background": _r(BACKGROUNDS[preset])}


# ---------------------------------------------------------------- camera

def _centre(target):
    """Centre point (x, z) of an object, a figure or a given [x, z] / [x, y, z]."""
    if isinstance(target, str):
        lo, hi = _world_bounds(_obj(target))
        return Vector(((lo.x + hi.x) / 2, (lo.z + hi.z) / 2))
    return Vector((target[0], target[-1]))


def _cam_put(cam, c, width=None):
    cam.location = (c.x, CAM_Y, c.y)
    if width is not None:
        cam.data.ortho_scale = width


def set_camera(look_at=None, width=None):
    """Centre the view on an object or a point [x, z]; `width` = metres visible across the frame."""
    scn = bpy.context.scene
    cam = scn.camera
    cam.animation_data_clear()
    cam.data.animation_data_clear()
    c = _centre(look_at) if look_at is not None else Vector((cam.location.x, cam.location.z))
    w = width or cam.data.ortho_scale
    if isinstance(look_at, str):
        lo, hi = _world_bounds(_obj(look_at))
        if lo.z < 0.05:
            # something standing on the ground: keep the ground line in the shot (15% up from the
            # bottom) unless the object is too tall for that, then fit its top
            h = w / ASPECT
            c.y = max(0.35 * h, hi.z + 0.08 * h - 0.5 * h)
    _cam_put(cam, c, width)
    cam["look_at"] = look_at if isinstance(look_at, str) else _r(c)
    w = cam.data.ortho_scale
    return {"centre": _r(c), "width": round(w, 2), "height": round(w / ASPECT, 2),
            "shows_x": [round(c.x - w / 2, 2), round(c.x + w / 2, 2)],
            "shows_z": [round(c.y - w / ASPECT / 2, 2), round(c.y + w / ASPECT / 2, 2)]}


def _look_at(cam):
    v = cam.get("look_at")
    return v if isinstance(v, str) else _r(v) if v is not None else None


def _smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def _key_linear(id_data, path):
    for fc in _fcurves(id_data):
        if fc.data_path == path:
            for k in fc.keyframe_points:
                k.interpolation = "LINEAR"


def camera_move(kind, target=None, start_frame=None, end_frame=None, amount=None):
    """pan / zoom_in / zoom_out / follow between start and end frame, eased in and out."""
    scn = bpy.context.scene
    cam = scn.camera
    s = scn.frame_start if start_frame is None else start_frame
    e = scn.frame_end if end_frame is None else end_frame
    if e <= s:
        raise ToolError(f"end_frame ({e}) must be after start_frame ({s})")
    if kind == "orbit":
        raise ToolError("the world is 2D (seen from the side), so the camera can't orbit. "
                        "Use pan, zoom_in, zoom_out or follow")
    if kind == "follow" and not isinstance(target, str):
        raise ToolError("follow needs the name of the object to follow as target")
    scn.frame_set(s)
    c0 = Vector((cam.location.x, cam.location.z))
    w0 = cam.data.ortho_scale
    if target is None:
        target = cam.get("look_at")
        target = target if isinstance(target, str) else list(target)

    def key(f, c, w):
        _cam_put(cam, c, w)
        cam.keyframe_insert("location", frame=f)
        cam.data.keyframe_insert("ortho_scale", frame=f)

    if kind in ("pan", "zoom_in", "zoom_out"):
        c1 = _centre(target)
        if kind == "pan":
            w1 = w0
            c1 = Vector((c1.x, c0.y))                    # slide sideways, keep the ground line still
        else:
            factor = amount or (0.6 if kind == "zoom_in" else 1.5)
            w1 = w0 * factor
            # zoom toward the target but keep the ground at the same place in the frame
            ground_frac = (0 - (c0.y - w0 / ASPECT / 2)) / (w0 / ASPECT)
            c1 = Vector((c1.x, w1 / ASPECT * (0.5 - ground_frac)))
        for f in range(s, e + 1):
            t = _smooth((f - s) / (e - s))
            key(f, c0.lerp(c1, t), w0 + (w1 - w0) * t)
    else:  # follow: keep the target's centre where it is on screen, smoothed (no walk-bob jitter)
        o = _obj(target)
        xs = {}
        for f in range(s, e + 1):
            scn.frame_set(f)
            xs[f] = _centre(o.name).x
        off = c0.x - xs[s]
        for f in range(s, e + 1):
            win = [xs[g] for g in range(max(s, f - 6), min(e, f + 6) + 1)]
            key(f, Vector((sum(win) / len(win) + off, c0.y)), w0)
    _key_linear(cam, "location")
    _key_linear(cam.data, "ortho_scale")
    cam["look_at"] = target if isinstance(target, str) else list(target)
    scn.frame_set(s)
    return {"kind": kind, "target": target if isinstance(target, str) else _r(target),
            "frames": [s, e], "start_centre": _r(c0), "start_width": round(w0, 2)}


# ---------------------------------------------------------------- keyframes

def _not_held(o, frame):
    """Keyframes before an object is first picked up are fine; from then on a hand moves it."""
    for f in FIGURES.values():
        for h in f.holds:
            if h["obj"] == o.name and frame >= h["from"] - 1:
                raise ToolError(f"'{o.name}' is picked up by '{f.name}' at frame {h['from']}: from then on it "
                                "moves with the hand (key it before that, or use put_down)")


def keyframe(name, property, frame, value):
    o = _obj(name)
    _no_figure(o, "figures are animated with play_action")
    if property in ("location", "rotation"):
        _not_held(o, frame)
    scn = bpy.context.scene
    scn.frame_set(frame)
    if property == "location":
        _place(o, value)
        o.keyframe_insert("location", frame=frame)
    elif property == "rotation":
        o.rotation_euler = _rotation(value)
        o.keyframe_insert("rotation_euler", frame=frame)
    elif property == "scale":
        o.scale = [value] * 3 if isinstance(value, (int, float)) else value
        o.keyframe_insert("scale", frame=frame)
    elif property == "colour":
        m = _material(o)
        _apply_colour(m, _rgb(value))
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
    _no_figure(o, "play_action already eases a figure's motion")
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


# ---------------------------------------------------------------- stick figures
#
# A figure is one curve object, drawn like a hand-made stick figure: thick strokes with round ends
# and round joints (a small disc at every joint: a very short tube seen end-on), a big filled disc for
# the head, short feet. Its points are keyframed every frame from motion.Figure, which plays the
# motion library. Limbs on the far side sit slightly behind and are drawn a little lighter.

CHAINS = [("body", ["pelvis", "chest", "neck"]),
          ("l", ["@shoulders", "l_shoulder", "l_elbow", "l_wrist"]),
          ("r", ["@shoulders", "r_shoulder", "r_elbow", "r_wrist"]),
          ("l", ["pelvis", "l_hip", "l_knee", "@l_foot", "l_toe"]),
          ("r", ["pelvis", "r_hip", "r_knee", "@r_foot", "r_toe"])]
SLOT = {"body": 0, "l": 1, "r": 2}
HEAD_R = 0.55 * motion.HEAD             # head radius in leg units (a touch bigger than the head bone)
FOOT_SHOWN = 0.5                        # the drawn foot is half as long as the ankle→toe bone
FOOT_FLAT = 30.0                        # ... turned this much about the toe, so planted feet lie flat
# every spline: (material slot, what it is); _point_positions returns points in this order
LAYOUT = ([(SLOT[side], "line") for side, _ in CHAINS] +
          [(SLOT[side], "joint") for side, chain in CHAINS for _ in chain] + [(0, "head")])


def _far_tone(rgb):
    """The far side's tone: lighter for dark figures, darker for light ones."""
    lum = sum(rgb) / 3
    return tuple(c + (1 - c) * 0.3 for c in rgb) if lum < 0.5 else tuple(c * 0.75 for c in rgb)


def _disc(c, depth=0.003):
    return [(c[0], c[1] - depth, c[2]), (c[0], c[1] + depth, c[2])]


def _point_positions(pose, foot_len):
    """Curve point positions for one world pose, in LAYOUT order: the strokes, a disc on every
    stroke point (round ends and joints), the head."""
    sh = tuple((a + b) / 2 for a, b in zip(pose["l_shoulder"], pose["r_shoulder"]))
    named = {"@shoulders": (sh[0], pose["chest"][1], sh[2])}
    for s in "lr":
        # the drawn foot is the front part of the ankle→toe bone, turned 30° about the toe so a
        # planted foot lies flat on the ground (the bone itself slopes down at -30°)
        a, t = pose[f"{s}_ankle"], pose[f"{s}_toe"]
        vx, vz = t[0] - a[0], t[2] - a[2]
        n = math.hypot(vx, vz) or 1.0
        rot = math.radians(FOOT_FLAT if vx >= 0 else -FOOT_FLAT)
        fx = (vx * math.cos(rot) - vz * math.sin(rot)) / n
        fz = (vx * math.sin(rot) + vz * math.cos(rot)) / n
        k = foot_len                         # one length for every foot, whatever the pose stretched
        named[f"@{s}_foot"] = (t[0] - fx * k, a[1], t[2] - fz * k)
    strokes = [[named.get(j) or pose[j] for j in chain] for _, chain in CHAINS]
    out = list(strokes)
    out += [_disc(p) for stroke in strokes for p in stroke]
    nk, top = pose["neck"], pose["head_top"]
    out.append(_disc(((nk[0] + top[0]) / 2, nk[1], (nk[2] + top[2]) / 2), 0.01))
    return out


def _build_figure_object(name, fig, rgb):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = fig.r
    cu.bevel_resolution = 6
    cu.use_fill_caps = True
    for part in ["body", "l", "r"]:
        cu.materials.append(bpy.data.materials.new(f"{name}_{part}"))
    pts = _point_positions(fig.poses[min(fig.poses)], FOOT_SHOWN * motion.FOOT * fig.L)
    for (slot, what), chain in zip(LAYOUT, pts):
        sp = cu.splines.new("POLY")
        sp.points.add(len(chain) - 1)
        sp.material_index = slot
        if what == "head":
            for p in sp.points:
                p.radius = HEAD_R * fig.L / fig.r
    o = bpy.data.objects.new(name, cu)
    o["kind"] = "figure"
    bpy.context.scene.collection.objects.link(o)
    _figure_colour(o, rgb)
    return o


def _figure_colour(o, rgb):
    o["colour"] = list(rgb)
    for m in o.data.materials:
        m.animation_data_clear()
        _apply_colour(m, rgb)
    _key_figure(o)


def _key_figure(o):
    """Write the figure's whole timeline into keyframes (points every frame, side tones per facing)."""
    fig = FIGURES[o.name]
    cu = o.data
    cu.animation_data_clear()
    scn = bpy.context.scene
    frames = fig.frames(max(scn.frame_end, fig.end))
    fs = sorted(frames)
    per_frame = {f: _point_positions(frames[f], FOOT_SHOWN * motion.FOOT * fig.L) for f in fs}
    for k, sp in enumerate(cu.splines):
        for j, p in enumerate(sp.points):
            x, y, z = per_frame[fs[0]][k][j]
            p.co = (x, y, z, 1.0)
            p.keyframe_insert("co", frame=fs[0])
    curves = {}
    for fc in _fcurves(cu):
        curves[(fc.data_path, fc.array_index)] = fc
    for k, sp in enumerate(cu.splines):
        for j, p in enumerate(sp.points):
            for a in range(3):
                fc = curves.get((f"splines[{k}].points[{j}].co", a))
                if fc is None:
                    continue
                fc.keyframe_points.add(len(fs) - 1)
                co = []
                for f in fs:
                    co += [f, per_frame[f][k][j][a]]
                fc.keyframe_points.foreach_set("co", co)
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"
                fc.update()
    # far-side tone follows the facing: facing right shows the left side far away, and vice versa
    rgb = tuple(o["colour"])
    far = _far_tone(rgb)
    mats = {"l": cu.materials[1], "r": cu.materials[2]}
    for m in mats.values():
        m.animation_data_clear()
    last = None
    for f in fs:
        facing = fig.local[f][2] if f in fig.local else last
        if facing == last:
            continue
        for side, m in mats.items():
            is_far = (facing == "right" and side == "l") or (facing == "left" and side == "r")
            m.diffuse_color = (*(far if is_far else rgb), 1.0)
            m.keyframe_insert("diffuse_color", frame=f)
        last = facing
    for m in mats.values():
        for fc in _fcurves(m):
            for kp in fc.keyframe_points:
                kp.interpolation = "CONSTANT"
    for obj in {h["obj"] for h in fig.holds}:
        _key_object_path(obj)


def _hand(pose):
    """Where a carried thing's centre goes: the right hand (the round end of the forearm)."""
    return pose["r_wrist"]


def _key_object_path(name):
    """Everything that happens to an object passed around by figures, in order: its own animation
    up to the first grab (a ball bouncing in is kept), then in a hand (drawn just in front of it),
    put somewhere, picked up again..."""
    o = bpy.data.objects.get(name)
    holds = sorted((h for f in FIGURES.values() for h in f.holds if h["obj"] == name and "home" in h),
                   key=lambda h: h["from"])
    if o is None or not holds:
        return
    first = holds[0]["from"] - 1
    for fc in [fc for fc in _fcurves(o) if fc.data_path in ("location", "rotation_euler")]:
        for kp in [kp for kp in fc.keyframe_points if kp.co.x >= first][::-1]:
            fc.keyframe_points.remove(kp)
        if not len(fc.keyframe_points):
            o.animation_data.action.fcurves.remove(fc)
    scn = bpy.context.scene
    off = Vector(holds[0]["offset"])
    pos = Vector(holds[0]["home"]) - off                     # the object's centre and tilt
    rot = holds[0].get("home_rot", 0.0)
    keys = []                                               # (frame, centre, rotation°, constant?)
    for h in holds:
        fig = FIGURES[next(f for f in FIGURES if h in FIGURES[f].holds)]
        frames = fig.frames(scn.frame_end)
        if h["from"] - 1 >= scn.frame_start:
            keys.append((h["from"] - 1, pos.copy(), rot, False))
        end = h["to"] if h["to"] is not None else max(frames)
        for f in range(h["from"], end + 1):
            x, y, z = _hand(frames[f])
            keys.append((f, Vector((x, y - 0.08, z)), rot, False))
        if h["to"] is None:
            break
        if h.get("rest"):
            pos = Vector((h["rest"][0], h["home"][1], h["rest"][2]))
            keys.append((h["to"] + 1, pos.copy(), rot, False))
    for f, c, r, _ in keys:
        o.location = c + off
        o.rotation_euler = (0.0, math.radians(r), 0.0)
        o.keyframe_insert("location", frame=f)
        o.keyframe_insert("rotation_euler", frame=f)
    for fc in _fcurves(o):                                  # only our keys go linear
        if fc.data_path in ("location", "rotation_euler"):
            for kp in fc.keyframe_points:
                if kp.co.x >= first:
                    kp.interpolation = "LINEAR"


def _overlap(name):
    """Another figure in the same layer standing where `name` ends up (pelvises < 0.4 m apart)."""
    fig = FIGURES[name]
    x = fig.pelvis_x(fig.end)
    for other, of in FIGURES.items():
        if other == name or abs(of.y - fig.y) > 0.5:
            continue
        frames = [f for f in of.poses if f <= fig.end]
        ox = of.pelvis_x(max(frames) if frames else min(of.poses))
        if abs(ox - x) < 0.4:
            return other, x, ox
    return None


def add_stick_figure(name=None, location=(0, 0), colour="black", facing="front", height=1.7, layer=None,
                     holding=None, carry="front"):
    name = name or _default_name("figure")
    if bpy.data.objects.get(name):
        raise ToolError(f"an object named '{name}' already exists; pick another name")
    y = LAYERS[layer or "middle"]
    if isinstance(location, dict):
        if "on_top_of" in location:
            raise ToolError("stick figures stand on the ground; use [x, 0] or {\"next_to\": name}")
        t = _obj(location["next_to"])
        lo, hi = _world_bounds(t)
        gap = location.get("gap", 0.3) + 0.25 * height / 1.7
        x = hi.x + gap if location.get("side", "right") == "right" else lo.x - gap
    else:
        if len(location) >= 2 and abs(location[-1]) > 0.01:
            raise ToolError("stick figures stand on the ground: the height (z) must be 0")
        x = location[0]
        if len(location) == 3:
            y = location[1] if layer is None else y
    fig = motion.Figure(name, x, y, height=height, facing=facing, start=bpy.context.scene.frame_start)
    FIGURES[name] = fig
    if holding:
        t = _obj(holding)
        _no_figure(t, "a figure can't hold another figure")
        fig.start_holding(holding, carry)
        lo, hi = _world_bounds(t)
        fig.holds[-1]["home"] = list(t.location)
        fig.holds[-1]["offset"] = list(t.location - (lo + hi) / 2)
    _build_figure_object(name, fig, _rgb(colour))
    lo, hi = fig.bounds_x()
    return {"name": name, "x": round(x, 2), "facing": facing, "height": height, "layer": _layer_name(y),
            "width": round(hi - lo, 2),
            "actions": motion.ACTIONS}


def play_action(name, action, start_frame=None, cycles=None, seconds=None, to=None, distance=None,
                direction=None, speed=1.0, carry="front"):
    o = _obj(name)
    if o.get("kind") != "figure":
        raise ToolError(f"'{name}' is not a stick figure (add one with add_stick_figure)")
    fig = FIGURES[name]
    scn = bpy.context.scene
    to_x = look_at = partner_x = obj = obj_at = None
    rest = None
    if action == "pick_up":
        if not isinstance(to, str) or to in FIGURES:
            raise ToolError("pick_up needs `to`: the name of the object to pick up")
        t = _obj(to)
        if t.get("kind") in ASSETS and t.get("kind") not in ("box", "lamp"):
            raise ToolError(f"'{to}' is too big to pick up; small things (shapes, a box, a lamp) can be")
        if any(h["obj"] == to and h["to"] is None for f in FIGURES.values() for h in f.holds):
            raise ToolError(f"someone is already holding '{to}'")
        scn.frame_set(start_frame if start_frame is not None else fig.end + 1)
        lo, hi = _world_bounds(t)
        obj, obj_at = to, ((lo.x + hi.x) / 2, (lo.z + hi.z) / 2)
    elif action == "put_down":
        if not fig.holding:
            raise ToolError(f"'{name}' isn't holding anything")
        held = _obj(fig.holding)
        hlo, hhi = _world_bounds(held)
        half = (hhi.z - hlo.z) / 2
        before = [f for f in fig.poses if start_frame is None or f < start_frame]
        fx = fig._feet_x(fig.poses[max(before) if before else min(fig.poses)])
        if isinstance(to, str):                  # on a surface: its nearest part, a little way in
            t = _obj(to)
            lo, hi = _world_bounds(t)
            x = min(max(fx, lo.x + 0.15), hi.x - 0.15)
            if abs(x - fx) < 0.3:
                x = fx + (0.3 if (lo.x + hi.x) / 2 >= fx else -0.3)
            obj_at = (x, _support_top(t) + half)
        else:                                    # on the ground in front
            sign = -1 if fig.facing == "left" else 1
            obj_at = (fx + sign * 0.45, half)
        obj = fig.holding
        rest = obj_at
    if action == "handshake":
        if not isinstance(to, str) or to not in FIGURES or to == name:
            raise ToolError("handshake needs `to`: the name of the other stick figure")
        other = FIGURES[to]
        before = [f for f in other.poses if start_frame is None or f <= start_frame]
        partner_x = other.pelvis_x(max(before) if before else min(other.poses))
    elif to is not None and action == "look_down":
        # look at something: turn toward it and bend just enough
        if isinstance(to, str):
            t = _obj(to)
            lo, hi = _world_bounds(t)
            look_at = ((lo.x + hi.x) / 2, (lo.z + hi.z) / 2)
        else:
            look_at = (float(to), 0.0)
    elif to is not None and action in ("react", "sigh"):
        # face what caused it (side-view actions): turn toward that object
        t = _obj(to)
        lo, hi = (FIGURES[to].bounds_x() if to in FIGURES else (lambda b: (b[0].x, b[1].x))(_world_bounds(t)))
        before = [f for f in fig.poses if start_frame is None or f < start_frame]
        here = fig._feet_x(fig.poses[max(before) if before else min(fig.poses)])
        if direction is None:
            direction = "right" if (lo + hi) / 2 > here else "left"
    elif to is not None and action not in ("pick_up", "put_down"):
        if action not in motion.TRAVELS:
            raise ToolError(f"'to' works with walks, run ({', '.join(motion.TRAVELS)}) and look_down")
        if isinstance(to, str):
            t = _obj(to)
            if t.name == name:
                raise ToolError("a figure can't walk to itself")
            if to in FIGURES:
                lo, hi = FIGURES[to].bounds_x()
            else:
                b = _world_bounds(t)
                lo, hi = b[0].x, b[1].x
            before = [f for f in fig.poses if start_frame is None or f < start_frame]
            here = fig.pelvis_x(max(before) if before else min(fig.poses))
            small = t.get("kind") not in ASSETS or t.get("kind") in ("box", "lamp")
            gap = (0.45 + 0.5 * fig.L if to in FIGURES       # a conversation's distance
                   else 0.08 + 0.3 * fig.L if small          # just in front, within reach (crouching)
                   else 0.15 + 0.5 * fig.L)                  # a hand's width from a big prop
            to_x = lo - gap if (lo + hi) / 2 >= here else hi + gap
        else:
            to_x = float(to)
    kw = dict(direction=direction, speed=speed, fps=scn.render.fps, look_at=look_at, partner_x=partner_x,
              obj=obj, obj_at=obj_at, carry=carry)
    stepped = None
    before_state = copy.deepcopy(fig.__dict__)        # to undo an action that ends inside someone
    try:
        res = fig.play(action, start=start_frame, cycles=cycles, seconds=seconds, to_x=to_x, distance=distance, **kw)
    except ValueError as e:
        # just out of reach (within a couple of steps): step up to it first, as anyone would
        feet = fig._feet_x(fig.poses[fig.end]) if start_frame is None else None
        if "out of reach" not in str(e) or feet is None or abs(obj_at[0] - feet) > 2.5:
            raise ToolError(str(e))
        sign = 1 if obj_at[0] > feet else -1
        try:
            stepped = fig.play("walk", to_x=obj_at[0] - sign * 0.42, fps=scn.render.fps)
            res = fig.play(action, **kw)
        except ValueError as e2:
            raise ToolError(str(e2))
        res["stepped_closer"] = stepped["frames"]
    clash = _overlap(name)
    if clash:
        fig.__dict__.clear()
        fig.__dict__.update(before_state)
        other, x, ox = clash
        raise ToolError(f"that would end with '{name}' standing inside '{other}' (x {x:.2f} vs {ox:.2f}, same layer); "
                        f"nothing was changed. Stop further away, move '{other}' first, or use another layer")
    if action == "pick_up":
        o_obj = _obj(obj)
        scn.frame_set(max(fig.holds[-1]["from"] - 1, scn.frame_start))
        lo, hi = _world_bounds(o_obj)
        fig.holds[-1]["home"] = list(o_obj.location)
        fig.holds[-1]["home_rot"] = math.degrees(o_obj.rotation_euler.y)
        # where the origin sits relative to the object's centre (carried by its centre)
        fig.holds[-1]["offset"] = list(o_obj.location - (lo + hi) / 2)
        res["holding"] = obj
    elif action == "put_down":
        h = fig.holds[-1]
        h["rest"] = [rest[0], h["home"][1], rest[1]]
        res["put"] = {"name": obj, "on": to if isinstance(to, str) else "ground"}

    if fig.end + 12 > scn.frame_end:
        scn.frame_end = fig.end + 12            # a short hold after the last action
        res["clip_end_frame"] = scn.frame_end
    for other in FIGURES:                        # other figures hold their last pose to the new end
        _key_figure(bpy.data.objects[other])
    scn.frame_set(scn.frame_start)
    return res


# ---------------------------------------------------------------- state and rendering

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
        if o.type not in ("MESH", "CURVE"):
            continue
        entry = {"name": o.name, "kind": o.get("kind", "mesh")}
        if o.get("kind") == "figure":
            fig = FIGURES[o.name]
            entry.update({"colour": colour_name(o["colour"]), "x_at_start": round(fig.pelvis_x(min(fig.poses)), 2),
                          "x_at_end": round(fig.pelvis_x(fig.end), 2), "facing_at_end": fig.facing,
                          "layer": _layer_name(fig.y), **({"holding": fig.holding} if fig.holding else {}),
                          "actions": [{k: g[k] for k in ("action", "start", "end", "facing")} for g in fig.segments]})
        elif o.get("kind") != "ground":
            m = o.data.materials[0] if o.data.materials else None
            if m:
                entry["colour"] = colour_name(m.diffuse_color)
            entry["bottom_centre"] = _r(_bottom_centre(o))
            entry["size"] = _r(o.dimensions)
            entry["layer"] = _layer_name(o.location.y)
            if any(abs(a) > 1e-4 for a in o.rotation_euler):
                entry["rotation"] = _r([math.degrees(a) for a in o.rotation_euler], 1)
            anim = _anim_summary(o)
            if anim:
                entry["keyframes"] = anim
        objs.append(entry)
    cam = scn.camera
    w = cam.data.ortho_scale
    keys = sorted({int(k.co.x) for fc in _fcurves(cam) + _fcurves(cam.data) for k in fc.keyframe_points})
    state = {
        "frames": {"start": scn.frame_start, "end": scn.frame_end, "fps": scn.render.fps,
                   "seconds": round((scn.frame_end - scn.frame_start + 1) / scn.render.fps, 2)},
        "objects": objs,
        "camera": {"centre": [round(cam.location.x, 2), round(cam.location.z, 2)], "width": round(w, 2),
                   "shows_x": [round(cam.location.x - w / 2, 2), round(cam.location.x + w / 2, 2)],
                   **({"moves_between_frames": [keys[0], keys[-1]]} if keys else {})},
        "background": scn.get("light_preset"),
        "note": "bottom_centre = [x, depth, height of the object's bottom] at the first frame; "
                "the camera looks from the front, screen-left is -x",
    }
    scn.frame_set(cur)
    return state


def _render_settings(w, h):
    r = bpy.context.scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
    _flat_look()


def render_check(frames):
    global _render_count
    _render_count += 1
    scn = bpy.context.scene
    _render_settings(960, 540)
    scn.render.image_settings.file_format = "PNG"
    paths = []
    for f in frames:
        scn.frame_set(f)
        scn.render.filepath = os.path.join(OUT_DIR, f"check{_render_count:02d}_f{f:04d}.png")
        bpy.ops.render.render(write_still=True)
        paths.append(scn.render.filepath)
    return {"images": paths}


def render_final(filename="final.mp4"):
    scn = bpy.context.scene
    _render_settings(1280, 720)
    scn.render.image_settings.file_format = "FFMPEG"
    scn.render.ffmpeg.format, scn.render.ffmpeg.codec = "MPEG4", "H264"
    scn.render.ffmpeg.constant_rate_factor = "HIGH"
    scn.render.filepath = os.path.join(OUT_DIR, filename)
    scn.render.use_file_extension = False
    t = time.time()
    bpy.ops.render.render(animation=True)
    return {"video": scn.render.filepath, "seconds": round(time.time() - t, 1)}


def _eval_mesh(o, deps):
    """(world vertices, [(world centre, world normal)] per face) of o as drawn now."""
    eo = o.evaluated_get(deps)
    me = eo.to_mesh()
    mw = eo.matrix_world
    nm = mw.to_3x3().inverted_safe().transposed()
    verts = [mw @ v.co for v in me.vertices]
    faces = [(mw @ p.center, (nm @ p.normal).normalized(), [verts[i] for i in p.vertices]) for p in me.polygons]
    polys = [tuple(p.vertices) for p in me.polygons]
    eo.to_mesh_clear()
    return verts, faces, polys


def _visible_fraction(o, cam, deps):
    """Share of up to 12 points on o's camera-facing faces that the camera can see (nothing else in
    between). Points are face centres nudged 2 mm outward, so faces resting on the ground or a
    table don't count as hidden. The camera is orthographic: every ray runs along its view axis.
    None if o has no size or no face toward the camera."""
    lo, hi = _world_bounds(o)
    if (hi - lo).length < 1e-3:
        return None
    fwd = (cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))).normalized()
    _, faces, _ = _eval_mesh(o, deps)
    pts = []
    for c, n, vs in faces:
        if n.z > -0.5 and n.dot(-fwd) > 0:
            # the face centre and points part-way to its corners, so a big face isn't judged by one point
            pts += [p + n * 0.002 for p in [c] + [c + (v - c) * 0.7 for v in vs]]
    if not pts:
        return None
    pts = pts[::max(1, len(pts) // 24)][:24]
    seen = 0
    cam_pos = cam.matrix_world.translation
    for p in pts:
        origin = p - fwd * ((p - cam_pos).dot(fwd))
        dist = (p - origin).length
        ok, _loc, _n, _i, hit, _m = bpy.context.scene.ray_cast(deps, origin, fwd, distance=max(dist - 0.001, 0))
        seen += (not ok) or (hit is not None and hit.original.name == o.name)
    return seen / len(pts)


def _world_bvh(o, deps):
    """BVH of o in world space, shrunk 1 cm per side so resting contact doesn't count as a collision."""
    from mathutils.bvhtree import BVHTree
    verts, _, polys = _eval_mesh(o, deps)
    lo, hi = _world_bounds(o)
    c, d = (lo + hi) / 2, hi - lo
    s = Vector([max(0.0, 1 - 0.02 / x) if x > 0 else 1.0 for x in d])
    verts = [c + Vector(((v - c).x * s.x, (v - c).y * s.y, (v - c).z * s.z)) for v in verts]
    return BVHTree.FromPolygons(verts, polys)


def sample_scene(vis_step=6):
    """Per-frame data the checker needs (checks/ evaluates it outside Blender)."""
    from bpy_extras.object_utils import world_to_camera_view
    scn = bpy.context.scene
    cam = scn.camera
    objs = _things()
    out = {"start": scn.frame_start, "end": scn.frame_end, "fps": scn.render.fps,
           "light": scn.get("light_preset"), "frames": [], "camera": [], "collisions": [],
           "objects": {o.name: {"kind": o.get("kind", "mesh"),
                                "top_z": o.get("top_z"), "frames": []} for o in objs},
           "figures": {}}
    tracks = {}
    for name, fig in FIGURES.items():
        out["figures"][name] = {"segments": fig.segments, "radius": fig.r, "leg": round(fig.L, 4),
                                "holds": [{k: h[k] for k in ("obj", "from", "to")} for h in fig.holds],
                                "joints": {j: [] for j in motion.JOINTS}}
        tracks[name] = fig.frames(scn.frame_end)
    for f in range(scn.frame_start, scn.frame_end + 1):
        scn.frame_set(f)
        deps = bpy.context.evaluated_depsgraph_get()
        key = (f - scn.frame_start) % vis_step == 0 or f == scn.frame_end
        out["frames"].append(f)
        q = cam.matrix_world.to_quaternion()
        cam_pos = cam.matrix_world.translation.copy()
        out["camera"].append({"loc": _r(cam_pos, 3), "fwd": _r(q @ Vector((0, 0, -1)), 3),
                              "right": _r(q @ Vector((1, 0, 0)), 3), "width": round(cam.data.ortho_scale, 3)})
        boxes = {}
        for o in objs:
            lo, hi = _world_bounds(o)
            boxes[o.name] = (lo, hi)
            corners = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
            sc = [world_to_camera_view(scn, cam, c) for c in corners]
            if o.get("kind") == "figure":
                colour = list(o["colour"])
            else:
                m = o.data.materials[0] if o.data.materials else None
                colour = list(m.diffuse_color[:3]) if m else None
            e = {"lo": _r(lo, 3), "hi": _r(hi, 3),
                 "rot": _r([math.degrees(a) for a in o.rotation_euler], 1), "scale": _r(o.scale, 3),
                 "colour": _r(colour, 3) if colour else None,
                 "screen": _r([min(p.x for p in sc), min(p.y for p in sc), max(p.x for p in sc),
                               max(p.y for p in sc)], 3),
                 "in_front": all(p.z > 0 for p in sc)}
            if key:
                e["visible"] = _visible_fraction(o, cam, deps)
            out["objects"][o.name]["frames"].append(e)
        for name, track in tracks.items():
            pose = track.get(f) or track[min(track)]
            for j in motion.JOINTS:
                out["figures"][name]["joints"][j].append(list(pose[j]))
        if key:
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
    camera_move, keyframe, set_easing, set_frames, add_stick_figure, play_action, render_check, render_final,
    sample_scene, set_output, save_blend)}
