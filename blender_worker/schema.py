"""Tool definitions the LLM sees (Ollama / OpenAI function format) and a validator with clear messages.

Validation happens here, outside Blender, so a bad call never reaches the worker and the model gets
an error it can act on. Numeric strings ("1.5") are accepted but recorded as warnings, so the
valid-tool-call rate in the evaluation still sees them.
"""
import copy

COLOUR_NAMES = ["red", "orange", "yellow", "green", "blue", "purple", "pink", "white", "black", "grey", "brown"]
ACTIONS = ["walk", "walk_happy", "walk_sad", "walk_worried", "run", "wave", "idle", "look_down", "react",
           "handshake", "pick_up", "put_down"]

VEC2 = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}
VEC3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
COLOUR = {"oneOf": [{"type": "string"}, VEC3],
          "description": f"a name ({', '.join(COLOUR_NAMES)}), '#rrggbb' or [r, g, b] in 0..1"}
PLACEMENT = {
    "type": "object",
    "properties": {
        "on_top_of": {"type": "string"},
        "offset": {"type": "array", "items": {"type": "number"}, "minItems": 1, "maxItems": 1},
        "next_to": {"type": "string"},
        "side": {"type": "string", "enum": ["left", "right"]},
        "gap": {"type": "number", "minimum": 0},
    },
    "oneOf_keys": ["on_top_of", "next_to"],
}
LOCATION = {
    "oneOf": [VEC2, VEC3, PLACEMENT],
    "description": "[x, z]: x = left/right (screen-left is negative), z = height of the object's BOTTOM "
                   "(0 = on the ground); or a placement: {\"on_top_of\": name}, "
                   "{\"next_to\": name, \"side\": \"left|right\", \"gap\": metres}",
}
LAYER = {"type": "string", "enum": ["back", "middle", "front"],
         "description": "depth layer (default middle): front is drawn over back; different layers never collide"}
ROTATION = {"oneOf": [{"type": "number"}, VEC3],
            "description": "degrees in the picture plane, positive = clockwise on screen"}
TARGET = {"oneOf": [{"type": "string"}, VEC2, VEC3], "description": "an object's name or a point [x, z]"}


def _tool(name, description, props=None, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props or {}, "required": list(required)}}}


TOOLS = [
    _tool("scene_reset", "Start an empty 2D scene (seen from the side, like paper): ground line at z = 0, "
                         "camera centred on [0, 1.6] showing 8 m across, white background, frames 1-72 at 24 fps."),
    _tool("scene_state", "Describe the current scene: objects (kind, colour, bottom_centre, size, layer, "
                         "keyframes), stick figures (actions, start/end x, facing), camera and frame range."),
    _tool("add_primitive", "Add a basic shape. It rests at `location` (bottom of the shape at z).",
          {"type": {"type": "string", "enum": ["cube", "sphere", "cylinder", "plane", "cone", "torus"]},
           "name": {"type": "string", "description": "unique name, e.g. 'ball' (default: the shape's name)"},
           "location": LOCATION,
           "size": {"type": "number", "minimum": 0.01, "maximum": 20, "description": "largest dimension in metres"},
           "colour": COLOUR, "layer": LAYER,
           "preset": {"type": "string", "enum": ["matte", "plastic", "metal", "glass", "glow", "wood"]}},
          ["type"]),
    _tool("add_asset", "Add a ready-made prop, drawn in profile. Tables, chairs, benches and boxes can hold "
                       "things ({\"on_top_of\": name}). Sizes: table 1.2 m wide x 0.75 m high, chair seat 0.46 m "
                       "high, bench 1.5 m long, box 0.5 m, lamp 0.46 m (a table lamp), tree 2.7 m. "
                       "Put things a figure walks past in the back layer.",
          {"asset": {"type": "string", "enum": ["table", "chair", "bench", "box", "lamp", "tree"]},
           "name": {"type": "string"}, "location": LOCATION, "layer": LAYER,
           "scale": {"type": "number", "minimum": 0.1, "maximum": 10}, "colour": COLOUR,
           "facing": {"type": "string", "enum": ["left", "right"], "description": "which way a chair faces"}},
          ["asset"]),
    _tool("set_transform", "Move, rotate or scale an existing object (not a stick figure).",
          {"name": {"type": "string"}, "location": LOCATION, "rotation": ROTATION, "layer": LAYER,
           "scale": {"oneOf": [{"type": "number", "minimum": 0}, VEC3]}},
          ["name"]),
    _tool("set_material", "Set an object's (or a stick figure's) colour.",
          {"name": {"type": "string"}, "colour": COLOUR,
           "preset": {"type": "string", "enum": ["matte", "plastic", "metal", "glass", "glow", "wood"]}},
          ["name"]),
    _tool("add_light", "Set the mood of the background: day (white), studio (light grey), sunset (peach), "
                       "night (dark blue).",
          {"preset": {"type": "string", "enum": ["day", "studio", "sunset", "night"]}}, ["preset"]),
    _tool("set_camera", "Frame the shot: centre on an object or a point [x, z], and choose how many metres "
                        "are visible across (height = width x 9/16).",
          {"look_at": TARGET,
           "width": {"type": "number", "minimum": 1, "maximum": 60, "description": "metres across, default 8"}}),
    _tool("camera_move", "Animate the camera between two frames (eased in and out). pan: slide sideways to "
                         "the target; zoom_in / zoom_out: show less / more around the target (`amount` = width "
                         "factor, default 0.6 / 1.5); follow: keep a moving object (e.g. a walking figure) in the "
                         "same place on screen.",
          {"kind": {"type": "string", "enum": ["pan", "zoom_in", "zoom_out", "follow"]},
           "target": TARGET,
           "start_frame": {"type": "integer", "minimum": 0}, "end_frame": {"type": "integer", "minimum": 1},
           "amount": {"type": "number", "minimum": 0.1, "maximum": 5}},
          ["kind"]),
    _tool("keyframe", "Set a property of an object (not a stick figure) at a frame and record a keyframe. "
                      "Between keyframes Blender interpolates smoothly.",
          {"name": {"type": "string"},
           "property": {"type": "string", "enum": ["location", "rotation", "scale", "colour"]},
           "frame": {"type": "integer", "minimum": 0, "maximum": 2000},
           "value": {"description": "location: like `location` of add_primitive; rotation: degrees clockwise; "
                                    "scale: number or [x, y, z]; colour: like `colour`"}},
          ["name", "property", "frame", "value"]),
    _tool("set_easing", "Choose how a property moves between its keyframes. 'gravity' is for bounces, "
                        "jumps and falls (speeds up falling, slows down rising).",
          {"name": {"type": "string"},
           "property": {"type": "string", "enum": ["location", "rotation", "scale", "colour"]},
           "interpolation": {"type": "string", "enum": ["linear", "ease_in_out", "ease_in", "ease_out",
                                                        "gravity", "bounce", "elastic", "constant"]},
           "from_frame": {"type": "integer"}, "to_frame": {"type": "integer"}},
          ["name", "property", "interpolation"]),
    _tool("set_frames", "Set the clip's frame range and frame rate.",
          {"start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1, "maximum": 2000},
           "fps": {"type": "integer", "minimum": 1, "maximum": 60}},
          ["start", "end"]),
    _tool("add_stick_figure", "Add a stick figure (1.7 m tall) standing on the ground. facing: 'front' "
                              "(toward the camera), 'left' or 'right'.",
          {"name": {"type": "string"},
           "location": {"oneOf": [VEC2, VEC3, PLACEMENT],
                        "description": "[x, 0] or {\"next_to\": name, \"side\": \"left|right\"}"},
           "colour": COLOUR, "facing": {"type": "string", "enum": ["front", "left", "right"]},
           "height": {"type": "number", "minimum": 0.5, "maximum": 3}, "layer": LAYER},
          []),
    _tool("play_action", "Make a stick figure perform an action from the motion library, after its previous "
                         "action (or from start_frame), blending smoothly (it turns first if it must face "
                         "another way). Walks: walk, walk_happy, walk_sad, walk_worried, and run (for hurrying "
                         "or running away); give `to` (an object's name: stops beside it; or an x position), "
                         "`distance` (m), `seconds` or `cycles`, and `direction` (left/right). Others: wave "
                         "(at the camera), idle (stands, breathing), look_down (`to`: what to look at, e.g. a "
                         "ball on a table), react (a sudden fright), handshake (`to` = the other figure; both figures play it "
                         "with the same start_frame, standing about 0.8-1.1 m apart and facing each other), "
                         "pick_up (`to` = a small object within reach: walk to it first; it is then carried "
                         "in the right hand through later actions), put_down (`to` = a surface such as a "
                         "table, or leave it out for the ground in front). "
                         "speed: 1 = normal, 0.7 = slow, 1.4 = fast. "
                         "Waves and idles face the camera.",
          {"name": {"type": "string"}, "action": {"type": "string", "enum": ACTIONS},
           "start_frame": {"type": "integer", "minimum": 0},
           "to": {"oneOf": [{"type": "string"}, {"type": "number"}]},
           "distance": {"type": "number", "minimum": 0.1, "maximum": 50},
           "seconds": {"type": "number", "minimum": 0.2, "maximum": 60},
           "cycles": {"type": "number", "minimum": 0.5, "maximum": 30},
           "direction": {"type": "string", "enum": ["left", "right"]},
           "speed": {"type": "number", "minimum": 0.3, "maximum": 3}},
          ["name", "action"]),
    _tool("render_check", "Render quick preview images of some frames and return the check report.",
          {"frames": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 8}},
          ["frames"]),
    _tool("render_final", "Render the final video. Call once, when the scene is done."),
]
BY_NAME = {t["function"]["name"]: t["function"] for t in TOOLS}

# values for keyframe.value, chosen by keyframe.property
KEYFRAME_VALUE = {"location": LOCATION, "rotation": ROTATION,
                  "scale": {"oneOf": [{"type": "number", "minimum": 0}, VEC3]}, "colour": COLOUR}


class ValidationError(Exception):
    pass


def _check(value, schema, path, warnings, top_props):
    if "oneOf" in schema:
        errors = []
        for option in schema["oneOf"]:
            try:
                return _check(value, option, path, warnings, top_props)
            except ValidationError as e:
                errors.append((option, str(e)))
        # if the value's shape picks one option (a dict → placement), its error is the useful one
        same_shape = [msg for opt, msg in errors if _shape_matches(value, opt)]
        detail = same_shape[0] if len(same_shape) == 1 else f"{path}: got {value!r}"
        hint = schema.get("description") or " or ".join(m for _, m in errors)
        raise ValidationError(f"{detail}. Expected {hint}")
    t = schema.get("type")
    if t == "number" or t == "integer":
        if isinstance(value, str):
            try:
                value = float(value) if t == "number" else int(value)
                warnings.append(f"{path}: number given as a string")
            except ValueError:
                raise ValidationError(f"{path}: expected a number, got {value!r}")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(f"{path}: expected a number, got {value!r}")
        if t == "integer":
            if value != int(value):
                raise ValidationError(f"{path}: expected a whole number, got {value!r}")
            value = int(value)
        if "minimum" in schema and value < schema["minimum"]:
            raise ValidationError(f"{path}: must be ≥ {schema['minimum']}, got {value}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValidationError(f"{path}: must be ≤ {schema['maximum']}, got {value}")
        return value
    if t == "string":
        if not isinstance(value, str):
            raise ValidationError(f"{path}: expected text, got {value!r}")
        if "enum" in schema and value not in schema["enum"]:
            raise ValidationError(f"{path}: must be one of {schema['enum']}, got {value!r}")
        return value
    if t == "array":
        if not isinstance(value, list):
            raise ValidationError(f"{path}: expected a list, got {value!r}")
        n = len(value)
        if n < schema.get("minItems", 0) or n > schema.get("maxItems", 10 ** 6):
            lo, hi = schema.get("minItems"), schema.get("maxItems")
            size = f"{lo}" if lo == hi else f"{lo}–{hi}"
            raise ValidationError(f"{path}: expected a list of {size} items, got {n}")
        return [_check(v, schema["items"], f"{path}[{i}]", warnings, top_props) for i, v in enumerate(value)]
    if t == "object":
        if not isinstance(value, dict):
            raise ValidationError(f"{path}: expected an object, got {value!r}")
        props = schema.get("properties", {})
        for k in value:
            if k not in props:
                raise ValidationError(f"{path}: unknown field '{k}'" + _misplaced_hint({k: 0}, top_props))
        keys = schema.get("oneOf_keys")
        if keys and sum(k in value for k in keys) != 1:
            raise ValidationError(f"{path}: use exactly one of {keys}")
        return {k: _check(v, props[k], f"{path}.{k}", warnings, top_props) for k, v in value.items()}
    return value


def _shape_matches(value, schema):
    kind = {dict: "object", list: "array", str: "string"}.get(type(value), "number")
    return schema.get("type") == kind or (kind == "number" and schema.get("type") == "integer")


def _misplaced_hint(value, top_props):
    if isinstance(value, dict):
        stray = [k for k in value if k in top_props]
        if stray:
            return f". Hint: {', '.join(repr(k) for k in stray)} is a separate argument of this tool, not part of this field"
    return ""


def _points_as_lists(value, warnings, path):
    """Accept a point written as {"x": -1, "z": 0} (a natural guess) as [-1, 0], with a warning."""
    if isinstance(value, dict):
        if value and "x" in value and set(value) <= {"x", "y", "z"}:
            warnings.append(f"{path}: point given as {{x, z}}; read as a list")
            return [value["x"], value["y"], value["z"]] if "y" in value else [value["x"], value.get("z", 0)]
        return {k: _points_as_lists(v, warnings, f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_points_as_lists(v, warnings, path) for v in value]
    return value


def validate(tool, args):
    """Return (clean_args, warnings) or raise ValidationError with a message for the model."""
    if tool not in BY_NAME:
        raise ValidationError(f"unknown tool '{tool}'. Tools: {', '.join(BY_NAME)}")
    params = BY_NAME[tool]["parameters"]
    props = params["properties"]
    args = copy.deepcopy(args or {})
    if not isinstance(args, dict):
        raise ValidationError(f"{tool}: arguments must be an object")
    for r in params["required"]:
        if r not in args:
            raise ValidationError(f"{tool}: missing required argument '{r}'")
    warnings, clean = [], {}
    args = _points_as_lists(args, warnings, tool)
    for k, v in args.items():
        if k not in props:
            raise ValidationError(f"{tool}: unknown argument '{k}'. Arguments: {', '.join(props)}")
        schema = KEYFRAME_VALUE[args["property"]] if (tool, k) == ("keyframe", "value") else props[k]
        clean[k] = _check(v, schema, f"{tool}.{k}", warnings, props)
    return clean, warnings
