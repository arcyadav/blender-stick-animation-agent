"""A0: template baseline. Keyword rules turn a request into a fixed tool sequence; no LLM.

It is generic (it never looks at task ids): it finds object mentions ("three cubes", "a red ball"),
relations between them ("on a table", "to the left of the table", "with a ball on it"), one motion
("bounces three times", "spins once in 2 seconds", "rolls … across a table", "grows … then turns red"),
camera words (orbit, dolly, follow) and light words, then frames everything with the camera.
"""
import math
import re

COLOURS = ["red", "orange", "yellow", "green", "blue", "purple", "pink", "white", "black", "grey", "gray", "brown"]
SHAPES = {"ball": "sphere", "sphere": "sphere", "cube": "cube", "block": "cube", "cylinder": "cylinder",
          "can": "cylinder", "cone": "cone", "ring": "torus", "torus": "torus", "donut": "torus"}
ASSETS = ["table", "chair", "bench", "box", "lamp", "tree"]
NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
TIMES = {"once": 1, "twice": 2, "one time": 1, "two times": 2, "three times": 3, "four times": 4,
         "five times": 5, "3 times": 3, "2 times": 2, "4 times": 4}

_NOUNS = sorted(list(SHAPES) + ASSETS, key=len, reverse=True)
MENTION = re.compile(
    r"\b(?:(a|an|the|one|two|three|four|five|six)\s+)?(?:(?:big|small|large|little)\s+)?"
    rf"(?:({'|'.join(COLOURS)})\s+)?(?:(?:big|small|large|little)\s+)?({'|'.join(_NOUNS)})(e?s)?\b")
REL_END = re.compile(r"(on top of|onto|on|next to|beside|to the left of|to the right of|in front of|behind)\s*$")
FPS = 24
G = 9.81


class Obj:
    def __init__(self, name, noun, colour):
        self.name, self.noun, self.colour = name, noun, colour
        self.kind = SHAPES.get(noun, noun)
        self.asset = noun in ASSETS
        self.place = None            # placement dict or [x, y, z]
        self.size = None


def _parse_objects(text):
    mentions, objs, by_noun = [], [], {}
    for m in MENTION.finditer(text):
        art, colour, noun, plural = m.groups()
        noun = {"blocks": "block"}.get(noun, noun)
        count = NUMBERS.get(art, 1) if art != "the" else 0
        if plural and count == 1 and art not in ("a", "an", "one"):
            count = 2
        if art == "the" and noun in by_noun:
            mentions.append((m, by_noun[noun]))
            continue
        group = []
        for k in range(max(count, 1)):
            base = noun if count <= 1 else f"{noun}{k + 1}"
            name = base
            while any(o.name == name for o in objs):
                name += "_b"
            o = Obj(name, noun, colour if colour != "gray" else "grey")
            objs.append(o)
            group.append(o)
        by_noun.setdefault(noun, group)
        mentions.append((m, group))
    return mentions, objs


def _relations(text, mentions):
    """Fill .place on objects from the words between mentions."""
    for i, (m, group) in enumerate(mentions):
        nxt = mentions[i + 1] if i + 1 < len(mentions) else None
        seg = text[m.end(): nxt[0].start() if nxt else len(text)]
        subject = group
        # "a table with a ball on it" → the ball (this mention) on the previous object
        if re.search(r"^\s*on (it|them)\b", seg) and i > 0:
            for o in subject:
                o.place = {"on_top_of": mentions[i - 1][1][0].name}
            continue
        on_ground = re.search(r"\bon the (floor|ground)\b", seg)
        rel = REL_END.search(seg)
        if rel and nxt and not re.search(r"\b(rolls?|walks?|moves?|across)\b", seg):
            target = nxt[1][0].name
            word = rel.group(1)
            for o in subject:
                if word in ("on", "onto", "on top of"):
                    o.place = {"on_top_of": target}
                elif word in ("next to", "beside"):
                    o.place = {"next_to": target, "side": "right"}
                elif word.startswith("to the"):
                    o.place = {"next_to": target, "side": "left" if "left" in word else "right", "gap": 0.4}
                elif word == "in front of":
                    o.place = {"in_front_of": target, "distance": 0.8}
                elif word == "behind":
                    o.place = {"next_to": target, "side": "back", "gap": 0.5}
        elif on_ground:
            for o in subject:
                o.place = o.place or [0, 0, 0]


def _middle_colour(text, groups):
    m = re.search(rf"middle one(?: is)? ({'|'.join(COLOURS)})", text)
    if m:
        for g in groups:
            if len(g) >= 3:
                g[len(g) // 2].colour = m.group(1)


def _times(text, default=1):
    for k, v in sorted(TIMES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{k}\b", text):
            return v
    return default


class Template:
    """Runs a request on a BlenderWorker (or anything with .call(tool, **args))."""

    name = "A0"

    def run(self, request, w, log=None):
        text = request.lower()
        calls = []

        def call(tool, **args):
            calls.append({"tool": tool, "args": args})
            r = w.call(tool, **args)
            if log:
                log(tool, args, r)
            return r

        call("scene_reset")
        mentions, objs = _parse_objects(text)
        _relations(text, mentions)
        _middle_colour(text, [g for _, g in mentions])
        groups = []
        for _, g in mentions:
            if g not in groups:
                groups.append(g)

        # layout: groups in a row along x; objects placed relative to others come after their targets
        x = 0.0
        loose = [g for g in groups if g[0].place is None]
        width = sum(1.6 * len(g) for g in loose)
        x = -width / 2 + 0.8
        for g in loose:
            for o in g:
                o.place = [round(x, 2), 0, 0]
                x += 1.6
        done, extra_pts = set(), []
        order = sorted(objs, key=lambda o: isinstance(o.place, dict))
        results = {}
        while order:
            o = next(o for o in order if not isinstance(o.place, dict) or
                     list(o.place.values())[0] in done)
            order.remove(o)
            if o.asset:
                args = {"asset": o.noun, "name": o.name, "location": o.place}
                if o.colour:
                    args["colour"] = o.colour
                results[o.name] = call("add_asset", **args)
            else:
                small = isinstance(o.place, dict) and "on_top_of" in o.place
                args = {"type": o.kind, "name": o.name, "location": o.place, "size": 0.25 if small else 0.6}
                if o.colour:
                    args["colour"] = o.colour
                results[o.name] = call("add_primitive", **args)
            done.add(o.name)

        movers = [o for o in objs if not o.asset] or objs
        end = self._motion(text, movers[0] if movers else None, results, call, extra_pts) if objs else 72
        call("set_frames", start=1, end=end, fps=FPS)

        for word in ("sunset", "night", "studio"):
            if word in text:
                call("add_light", preset=word)

        self._frame_camera(results, extra_pts, call)
        self._camera_moves(text, objs, end, call)
        return calls

    # ---------------------------------------------------------------- motion

    def _motion(self, text, o, results, call, pts):
        if o is None:
            return 72
        r = results[o.name]
        x0, y0, z0 = r["bottom_centre"]
        size = r["size"][2]
        m = re.search(r"bounc", text)
        if m:
            n = _times(text[m.start():], default=1)
            keys, f, h, x = [], 1, 1.5, x0 - 2.0
            keys.append((f, x, h))
            for k in range(n + 1):
                f += max(4, round(math.sqrt(2 * h / G) * FPS))
                x += 4.0 / (2 * n + 1)
                keys.append((f, x, 0.0))
                if k == n:
                    break
                h *= 0.55
                f += max(4, round(math.sqrt(2 * h / G) * FPS))
                x += 4.0 / (2 * n + 1)
                keys.append((f, x, h))
            for f, x, z in keys:
                call("keyframe", name=o.name, property="location", frame=f, value=[round(x, 2), y0, round(z, 2)])
                pts.append((x, y0, z + size))
            call("set_easing", name=o.name, property="location", interpolation="gravity")
            return f + 12

        m = re.search(r"spins?|rotates?|turns? around", text)
        if m:
            turns = _times(text[m.start():], default=1)
            s = re.search(r"in (\d+(?:\.\d+)?) ?s(?:ec(?:ond)?s?)?\b", text)
            secs = float(s.group(1)) if s else 2.0
            start, stop = 13, 13 + round(secs * FPS)
            call("keyframe", name=o.name, property="rotation", frame=start, value=[0, 0, 0])
            call("keyframe", name=o.name, property="rotation", frame=stop, value=[0, 0, 360 * turns])
            call("set_easing", name=o.name, property="rotation", interpolation="linear")
            return stop + 12

        m = re.search(r"rolls? from (left|right) to (left|right) across (?:a|the) (\w+)", text)
        if m:
            support = results.get(m.group(3))
            sign = 1 if m.group(2) == "right" else -1
            rad = r["size"][0] / 2
            if support:
                sx, sy, _ = support["bottom_centre"]
                half = support["size"][0] / 2
                top = support.get("top_height", support["size"][2])
                # roll until the whole ball has cleared the edge, then drop
                xs = [sx - sign * (half - 0.15), sx + sign * (half + rad + 0.02)]
                keys = [(1, xs[0], top), (40, xs[1], top)]
                if re.search(r"(drops|falls)", text):
                    keys += [(50, xs[1] + sign * 0.3, 0.0), (68, xs[1] + sign * 0.8, 0.0)]
            else:
                keys = [(1, x0 - sign * 2, 0.0), (60, x0 + sign * 2, 0.0)]
                sy = y0
            for f, x, z in keys:
                call("keyframe", name=o.name, property="location", frame=f, value=[round(x, 2), sy, round(z, 3)])
                call("keyframe", name=o.name, property="rotation", frame=f,
                     value=[0, round(math.degrees((x - keys[0][1]) / rad), 1), 0])
                pts.append((x, sy, z + size))
            call("set_easing", name=o.name, property="location", interpolation="gravity")
            call("set_easing", name=o.name, property="rotation", interpolation="linear")
            return keys[-1][0] + 4

        if re.search(r"grows? from nothing|appears", text):
            call("keyframe", name=o.name, property="scale", frame=1, value=0)
            call("keyframe", name=o.name, property="scale", frame=24, value=1)
            call("set_easing", name=o.name, property="scale", interpolation="ease_out")
        m = re.search(rf"turns? ({'|'.join(COLOURS)})", text)
        if m:
            call("keyframe", name=o.name, property="colour", frame=36, value=o.colour or "white")
            call("keyframe", name=o.name, property="colour", frame=54, value=m.group(1))
        return 72

    # ---------------------------------------------------------------- camera

    def _frame_camera(self, results, pts, call):
        for r in results.values():
            (x, y, z), (sx, sy, sz) = r["bottom_centre"], r["size"]
            pts += [(x - sx / 2, y - sy / 2, z), (x + sx / 2, y + sy / 2, z + sz)]
        if not pts:
            return
        lo = [min(p[k] for p in pts) for k in range(3)]
        hi = [max(p[k] for p in pts) for k in range(3)]
        c = [(a + b) / 2 for a, b in zip(lo, hi)]
        w, d, h = hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]
        # 35 mm lens, 16:9: half-angles ≈ 27.2° wide, 16.1° high
        dist = max(w / (2 * 0.514), h / (2 * 0.289), 1.5) * 1.35 + d / 2
        call("set_camera", location=[round(c[0], 2), round(c[1] - dist, 2), round(c[2] + 0.3 * dist, 2)],
             look_at=[round(v, 2) for v in c])

    def _camera_moves(self, text, objs, end, call):
        def target_after(word):
            m = re.search(rf"{word}\w*(?: slowly)?(?: around| in on| towards?)? (?:a|the) (\w+)", text)
            if m:
                for o in objs:
                    if o.noun == m.group(1) or o.name == m.group(1):
                        return o.name
            return objs[0].name if objs else None

        if "orbit" in text:
            call("camera_move", kind="orbit", target=target_after("orbit"), start_frame=1, end_frame=end,
                 degrees=120 if "slow" in text else 180)
        elif "dolly" in text or "zooms in" in text:
            call("camera_move", kind="dolly_in", target=target_after("doll"), start_frame=1, end_frame=end)
        elif "follow" in text:
            call("camera_move", kind="follow", target=target_after("follow"), start_frame=1, end_frame=end)
