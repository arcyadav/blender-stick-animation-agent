"""A0: template baseline. Keyword rules turn a request into a fixed tool sequence; no LLM.

It is generic (it never looks at task ids): it finds object mentions ("three cubes", "a red ball"),
relations between them ("on a table", "to the left of the table", "with a ball on it"), one object
motion ("bounces three times", "spins once in 2 seconds", "rolls … across a table", "grows … then
turns red"), stick figures and what they do in order ("walks to the table and waves", "looks down
for 2 seconds"), camera words (pan, zoom, follow) and light words, then frames everything.
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
FIGURE = re.compile(rf"\b(?:(a|an|one|two|the other)\s+)?(?:(?:{'|'.join(COLOURS)}|sad|happy|worried)\s+)?"
                    rf"(?:and an? (?:{'|'.join(COLOURS)})\s+)?stick\s+(?:man|woman|figure)s?\b")
FPS = 24
G = 9.81


class Obj:
    def __init__(self, name, noun, colour):
        self.name, self.noun, self.colour = name, noun, colour
        self.kind = SHAPES.get(noun, noun)
        self.asset = noun in ASSETS
        self.place = None            # placement dict or [x, z]
        self.layer = None


def _parse_objects(text):
    mentions, objs, by_noun = [], [], {}
    for m in MENTION.finditer(text):
        art, colour, noun, plural = m.groups()
        noun = {"blocks": "block"}.get(noun, noun)
        count = NUMBERS.get(art, 1) if art != "the" else 0
        if plural and count == 1 and art not in ("a", "an", "one"):
            count = 2
        if art in ("the", None) and noun in by_noun or (art == "it" and noun in by_noun):
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
    """Fill .place / .layer on objects from the words between mentions."""
    for i, (m, group) in enumerate(mentions):
        nxt = mentions[i + 1] if i + 1 < len(mentions) else None
        seg = text[m.end(): nxt[0].start() if nxt else len(text)]
        subject = group
        # "a table with a ball on it" → the ball (this mention) on the previous object
        if re.search(r"^\s*on (it|them)\b", seg) and i > 0:
            for o in subject:
                o.place = {"on_top_of": mentions[i - 1][1][0].name}
            continue
        rel = REL_END.search(seg)
        # "sits on the bench" / "puts the ball on the table" are actions, not where things stand
        acted = re.search(r"\b(?:puts?|sets?|places?|drops?|picks? up|grabs?)\s+(?:the|a|an)?\s*$",
                          text[max(0, m.start() - 16): m.start()])
        # "a ball sits on a table" places the ball; "…to the table, sits on a chair" is the figure sitting
        sits = re.search(r"\b(sits?|stands?)\b", seg) and not re.match(r"\s*(sits?|stands?)\b", seg)
        if rel and nxt and nxt[1] is not group and not acted and not sits and \
                not re.search(r"\b(rolls?|walks?|moves?|across|looks?|stick)\b", seg):
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
                    o.place, o.layer = {"next_to": target, "side": "right", "gap": -0.6}, "front"
                elif word == "behind":
                    o.place, o.layer = {"next_to": target, "side": "right", "gap": -0.6}, "back"
        # "on the floor" needs nothing: loose objects are laid out on the ground anyway


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


def _seconds(text):
    m = re.search(r"(?:for|in) (\d+(?:\.\d+)?) ?s(?:ec(?:ond)?s?)?\b", text)
    return float(m.group(1)) if m else None


class Template:
    """Runs a request on a BlenderWorker (or anything with .call(tool, **args))."""

    name = "A0"

    def run(self, request, w, log=None, check=None, task_id=None):
        text = request.lower()
        calls = []

        def call(tool, **args):
            calls.append({"tool": tool, "args": args})
            r = w.call(tool, **args)
            if log:
                log(tool, args, None)
            return r

        call("scene_reset")
        figures = _parse_figures(text)
        mentions, objs = _parse_objects(text)
        _relations(text, mentions)
        _middle_colour(text, [g for _, g in mentions])
        groups = []
        for _, g in mentions:
            if g not in groups:
                groups.append(g)
        if figures:
            for o in objs:                       # props sit behind the figures' path
                o.layer = o.layer or ("back" if not isinstance(o.place, dict) else None)

        # layout: groups in a row along x; objects placed relative to others come after their targets
        loose = [g for g in groups if g[0].place is None]
        gap = 2.6 if figures else 1.6
        x = -gap * (sum(len(g) for g in loose) - 1) / 2
        for g in loose:
            for o in g:
                o.place = [round(x, 2), 0]
                x += gap
        done, extra_pts = set(), []
        order = list(objs)
        results = {}
        while order:
            o = next(o for o in order if not isinstance(o.place, dict) or
                     list(o.place.values())[0] in done)
            order.remove(o)
            args = {"name": o.name, "location": o.place}
            if o.layer:
                args["layer"] = o.layer
            if o.colour:
                args["colour"] = o.colour
            if o.asset:
                results[o.name] = call("add_asset", asset=o.noun, **args)
            else:
                small = isinstance(o.place, dict) and "on_top_of" in o.place
                size = (0.18 if small else 0.4) if o.kind == "sphere" else (0.25 if small else 0.6)
                results[o.name] = call("add_primitive", type=o.kind, size=size, **args)
            done.add(o.name)

        for word in ("sunset", "night", "studio"):
            if word in text:
                call("add_light", preset=word)

        self.centred = False
        if figures:
            end, path = _Figures(text, figures, results, call).run()
            extra_pts += path
            if "middle" in text:                     # "stops in the middle": the middle of the shot
                self.centred = True
            self.focus = [round(sum(p[0] for p in path) / len(path), 2), 0.9]
        else:
            movers = [o for o in objs if not o.asset] or objs
            end = self._motion(text, movers[0] if movers else None, results, call, extra_pts) if objs else 72
            call("set_frames", start=1, end=end, fps=FPS)

        self._frame_camera(results, extra_pts, call)
        self._camera_moves(text, objs, figures, end, call)
        return calls

    # ---------------------------------------------------------------- object motion

    def _motion(self, text, o, results, call, pts):
        if o is None:
            return 72
        r = results[o.name]
        x0, _, z0 = r["bottom_centre"]
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
                call("keyframe", name=o.name, property="location", frame=f, value=[round(x, 2), round(z, 2)])
                pts.append((x, z + size))
            call("set_easing", name=o.name, property="location", interpolation="gravity")
            # after the last bounce it keeps rolling a little and slows to a stop
            rad = r["size"][0] / 2
            roll = 0.35
            call("keyframe", name=o.name, property="location", frame=f + 18, value=[round(x + roll, 2), 0])
            call("set_easing", name=o.name, property="location", interpolation="ease_out", from_frame=f)
            call("keyframe", name=o.name, property="rotation", frame=f, value=0)
            call("keyframe", name=o.name, property="rotation", frame=f + 18, value=round(math.degrees(roll / rad)))
            call("set_easing", name=o.name, property="rotation", interpolation="ease_out")
            pts.append((x + roll, size))
            return f + 30

        m = re.search(r"spins?|rotates?|turns? around", text)
        if m:
            turns = _times(text[m.start():], default=1)
            secs = _seconds(text) or 2.0
            start, stop = 13, 13 + round(secs * FPS)
            call("keyframe", name=o.name, property="rotation", frame=start, value=0)
            call("keyframe", name=o.name, property="rotation", frame=stop, value=360 * turns)
            call("set_easing", name=o.name, property="rotation", interpolation="linear")
            return stop + 12

        m = re.search(r"rolls? from (left|right) to (left|right) across (?:a|the) (\w+)", text)
        if m:
            support = results.get(m.group(3))
            sign = 1 if m.group(2) == "right" else -1
            rad = r["size"][0] / 2
            if support:
                sx = support["bottom_centre"][0]
                half = support["size"][0] / 2
                top = support.get("top_height", support["size"][2])
                # roll until the ball's centre is past the edge, then fall while still moving on
                xs = [sx - sign * (half - 0.15), sx + sign * (half + 0.5 * rad)]
                keys = [(1, xs[0], top), (40, xs[1], top)]
                if re.search(r"(drops|falls)", text):
                    # falls (gravity), bounces twice, losing height, then rolls to a stop
                    x = xs[1]
                    for f, dx, z in ((50, 0.25, 0.0), (55, 0.4, 0.2), (60, 0.55, 0.0), (63, 0.63, 0.06),
                                     (66, 0.71, 0.0), (80, 0.95, 0.0)):
                        keys.append((f, x + sign * dx, z))
            else:
                keys = [(1, x0 - sign * 2, 0.0), (60, x0 + sign * 2, 0.0)]
            for f, x, z in keys:
                call("keyframe", name=o.name, property="location", frame=f, value=[round(x, 2), round(z, 3)])
                call("keyframe", name=o.name, property="rotation", frame=f,
                     value=round(sign * math.degrees(abs(x - keys[0][1]) / rad), 1))
                pts.append((x, z + size))
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
        pts = [(x, z) for x, z in pts]
        for r in results.values():
            (x, _, z), (sx, _, sz) = r["bottom_centre"], r["size"]
            pts += [(x - sx / 2, z), (x + sx / 2, z + sz)]
        if not pts:
            return
        lo_x, hi_x = min(p[0] for p in pts), max(p[0] for p in pts)
        if self.centred:
            hi_x = max(abs(lo_x), abs(hi_x))
            lo_x = -hi_x
        top = max(max(p[1] for p in pts), 1.0)
        # ground line 15% from the bottom; everything fits with a margin
        width = max((hi_x - lo_x) * 1.3 + 0.8, top / 0.75 * 16 / 9, 5.0)
        cz = 0.35 * width * 9 / 16
        call("set_camera", look_at=[round((lo_x + hi_x) / 2, 2), round(cz, 2)], width=round(width, 2))
        self.view = ((lo_x + hi_x) / 2, cz, width)

    def _camera_moves(self, text, objs, figures, end, call):
        names = [o.name for o in objs] + [f["name"] for f in figures]

        def target_after(word):
            m = re.search(rf"{word}\w*(?: slowly)?(?: around| in on| towards?| to| from)? (?:a|the) (\w+)", text)
            if m:
                for o in objs:
                    if o.noun == m.group(1) or o.name == m.group(1):
                        return o.name
            return names[0] if names else None

        if "pan" in text:
            m = re.search(r"pans? from (?:a|the) (\w+).*? to (?:a|the) (\w+)", text)
            first = next((o.name for o in objs if m and o.noun == m.group(1)), names[0])
            last = next((o.name for o in objs if m and o.noun == m.group(2)), names[-1])
            call("set_camera", look_at=first, width=5.5)
            call("camera_move", kind="pan", target=last, start_frame=12, end_frame=end - 12)
        elif "zoom" in text or "dolly" in text:
            call("camera_move", kind="zoom_in", target=target_after("zoom") if not figures else self.focus,
                 start_frame=1, end_frame=end)
        elif "follow" in text:
            tgt = figures[0]["name"] if figures else target_after("follow")
            call("set_camera", look_at=tgt, width=6)
            call("camera_move", kind="follow", target=tgt, start_frame=1, end_frame=end)


# ---------------------------------------------------------------- stick figures

def _parse_figures(text):
    """→ [{"name", "colour", "mood"}] in order of mention; 'he'/'she' alone means one figure."""
    out = []
    for m in FIGURE.finditer(text):
        art = m.group(1)
        words = m.group(0)
        colours = re.findall(rf"\b({'|'.join(COLOURS)})\b", words)
        mood = next((w for w in ("sad", "happy", "worried") if re.search(rf"\b{w}\b", words)), None)
        n = 2 if art == "two" or len(colours) == 2 else 1
        if art == "the other" and out:
            continue
        for k in range(n):
            out.append({"name": f"fig{len(out) + 1}", "colour": colours[k] if k < len(colours) else None,
                        "mood": mood})
        if art == "one" and re.search(r"\bthe other\b", text):
            out.append({"name": f"fig{len(out) + 1}", "colour": None, "mood": mood})
    if not out and re.search(r"^(she|he)\b", text):
        out.append({"name": "fig1", "colour": None, "mood": None})
    return out


WALK_WORDS = r"walks?|hurries|hurry|strolls?|runs?"


class _Figures:
    """Plans what each figure does, clause by clause, and plays it."""

    def __init__(self, text, figures, results, call):
        self.text, self.figs, self.results, self.call = text, figures, results, call

    def _prop(self, word):
        for name, r in self.results.items():
            if name.rstrip("0123456789") == word or name == word:
                return name
        return None

    def _events(self, text):
        """Ordered (kind, clause) events found in the text."""
        clauses = re.split(r",|;|\bthen\b|\band\b(?= (?:waves?|looks?|walks?|gets?|stops?|turns?|hurries|sits?|"
                           r"stands?|picks?|puts?|sets?|places?|sighs?|shakes?))", text)
        ev = []
        for c in clauses:
            before = len(ev)
            if re.search(r"\bstands? up\b|\bgets? up\b", c):
                ev.append(("stand_up", c))
            if re.search(rf"\b({WALK_WORDS})\b", c):
                ev.append(("walk", c))
            if re.search(r"\bpicks? (?:it |them )?up\b|\bpicks? (?:a|the) \w+ up\b|\bgrabs?\b", c):
                ev.append(("pick_up", c))
            if re.search(r"\b(?:puts?|sets?|places?|drops?) (?:it|them|(?:a|the) \w+)(?: \w+)?\b", c) and \
                    not re.search(r"\bdrops? off\b", c):
                ev.append(("put_down", c))
            if re.search(r"\bsits?\b|\btakes? a seat\b", c) and \
                    not re.search(rf"\b(?:{'|'.join(_NOUNS)})e?s? sits?\b", c):    # "a ball sits on a table"
                ev.append(("sit", c))
            if re.search(r"\bturns? (?:to (?:the )?)?(?:left|right|to face|towards?)\b", c):
                ev.append(("turn", c))
            if re.search(r"\bwaves?\b|\bwave together\b", c):
                ev.append(("wave", c))
            if re.search(r"looks? down", c):
                ev.append(("look_down", c))
            elif re.search(r"\blooks? (?:up|at|around|ahead|over|towards?|back)\b", c):
                ev.append(("look", c))
            if re.search(r"fright|startled|scared|shock", c):
                ev.append(("react", c))
            if re.search(r"\bsighs?\b", c):
                ev.append(("sigh", c))
            if re.search(r"stands? (still|around)|breathing|waits?", c):
                ev.append(("idle", c))
            if len(ev) == before and ev and _seconds(c):          # "…, for 3 seconds" belongs to the last one
                ev[-1] = (ev[-1][0], ev[-1][1] + " " + c)
        out = []
        for k, c in ev:                                           # "stands still, just breathing" = one idle
            if out and k == out[-1][0] and k != "walk":
                out[-1] = (k, out[-1][1] + " " + c)
            else:
                out.append((k, c))
        return out

    def run(self):
        t = self.text
        figs = self.figs
        path = []
        # two figures with their own roles
        if len(figs) == 2 and re.search(r"toward each other", t):
            self._add(figs[0], -3.0, "right")
            self._add(figs[1], 3.0, "left")
            path += [(-3.4, 1.7), (3.4, 1.7)]
            ra = self.call("play_action", name=figs[0]["name"], action="walk", to=-0.45)
            r = self.call("play_action", name=figs[1]["name"], action="walk", to=0.45)
            if re.search(r"shake hands|handshake", t):
                start = max(ra["frames"][1], r["frames"][1]) + 1
                self.call("play_action", name=figs[0]["name"], action="handshake", to=figs[1]["name"],
                          start_frame=start)
                r = self.call("play_action", name=figs[1]["name"], action="handshake", to=figs[0]["name"],
                              start_frame=start)
            return self._end(r), path
        if len(figs) == 2 and re.search(r"side by side", t) and re.search(rf"\b({WALK_WORDS})\b", t):
            d = "left" if re.search(r"right to (the )?left", t) else "right"
            s = -1 if d == "right" else 1
            self._add(figs[0], s * 3.4, d)
            self._add(figs[1], s * 2.5, d)
            self.call("play_action", name=figs[0]["name"], action="walk", seconds=4, direction=d)
            r = self.call("play_action", name=figs[1]["name"], action="walk", seconds=4, direction=d)
            path += [(s * 3.8, 1.7), (-s * 3.5, 1.7)]
            return self._end(r), path
        if len(figs) == 2 and re.search(r"side by side", t):
            self._add(figs[0], -0.45, "front")
            self._add(figs[1], 0.45, "front")
            act = "wave" if "wave" in t else "idle"
            self.call("play_action", name=figs[0]["name"], action=act, start_frame=1)
            r = self.call("play_action", name=figs[1]["name"], action=act, start_frame=1)
            path += [(-1.2, 1.7), (1.2, 1.7)]
            return self._end(r), path
        if len(figs) == 2 and re.search(r"the other", t):
            waver, walker = figs
            self._add(waver, 1.5, "front")
            self._add(walker, -3.0, "right")
            self.call("play_action", name=waver["name"], action="wave", start_frame=1)
            r = self.call("play_action", name=walker["name"], action="walk", to=waver["name"])
            path += [(-3.4, 1.7), (2.0, 1.7)]
            return self._end(r), path
        # one figure (any others just stand)
        return self._single(figs[0], path)

    def _add(self, fig, x, facing):
        args = {"name": fig["name"], "location": [round(x, 2), 0], "facing": facing}
        if fig.get("colour"):
            args["colour"] = fig["colour"]
        self.call("add_stick_figure", **args)

    def _end(self, r):
        return r.get("clip_end_frame") or r["frames"][1] + 12

    def _walk_kind(self, clause, mood):
        if re.search(r"\bsad(ly)?\b", clause):
            return "walk_sad"
        if re.search(r"\bhapp(y|ily)\b", clause):
            return "walk_happy"
        if re.search(r"\bworried\b", clause):
            return "walk_worried"
        return {"sad": "walk_sad", "happy": "walk_happy", "worried": "walk_worried"}.get(mood, "walk")

    def _single(self, fig, path):
        t = self.text
        events = self._events(t)
        name = fig["name"]
        walks = [c for k, c in events if k == "walk"]
        # where to start: opposite the first walk's goal
        first = walks[0] if walks else ""
        goal = None
        m = re.search(r"\b(?:to|up to|over to|towards?) (?:a|the) (\w+)", first)
        if m and self._prop(m.group(1)):
            goal = self._prop(m.group(1))
        m_from = re.search(r"from (?:the )?(left|right)(?: \w+)?(?: \w+)? (\w+)? ?to (?:the )?(left|right)", first)
        left_first = bool(re.search(r"to the left|off to the left|\bleft\b(?! side of)", first)) and not re.search(
            r"from the left|in from the left|left (box|side)", first)
        x0 = 3.0 if left_first else -3.0
        goals = [self._prop(g) for c in walks for g in re.findall(r"\b(?:to|past) (?:a|the) (\w+)", c)]
        goals = [g for g in goals if g]
        if goal:
            gx = self.results[goal]["bottom_centre"][0]
            x0 = gx - 3.2 if gx >= 0 else gx + 3.2
            if goals and goals[-1] != goal:          # more stops later: start on the far side of the first
                lx = self.results[goals[-1]]["bottom_centre"][0]
                x0 = gx - 2.5 if lx > gx else gx + 2.5
        m_box = re.search(r"from the (left|right) (\w+?)s? to the (left|right)", first)
        if m_box:
            items = sorted([n for n in self.results if n.rstrip("0123456789") == m_box.group(2)],
                           key=lambda n: self.results[n]["bottom_centre"][0])
            if items:
                start_item = items[0] if m_box.group(1) == "left" else items[-1]
                x0 = self.results[start_item]["bottom_centre"][0] + (0.75 if m_box.group(1) == "left" else -0.75)
        elif m_from:
            x0 = -3.2 if m_from.group(1) == "left" else 3.2
        if re.search(r"in from the left", first):
            x0 = -4.2
        elif re.search(r"in from the right", first):
            x0 = 4.2
        facing = "front" if not walks or events[0][0] != "walk" else ("left" if x0 > 0 else "right")
        self._add(fig, x0, facing)
        path.append((x0, 1.7))
        start_x = x0
        here = x0
        r = None
        last_target = last_dir = None
        for kind, clause in events:
            secs = _seconds(clause)
            if kind == "walk":
                args = {"name": name, "action": self._walk_kind(clause, fig.get("mood"))}
                if re.search(r"\bslow(ly)?\b", clause):
                    args["speed"] = 0.7
                if re.search(r"hurr(y|ies)|quickly|fast|\bruns?\b", clause):
                    args["action"] = "run"
                target = re.search(r"\b(?:to|up to|over to|towards?) (?:a|the) (\w+)", clause) or re.search(
                    r"\bpast (?:a|the) (\w+)", clause)
                prop = self._prop(target.group(1)) if target else None
                if m_box and re.search(r"to the (left|right) \w+", clause):
                    items = sorted([n for n in self.results if n.rstrip("0123456789") == m_box.group(2)],
                                   key=lambda n: self.results[n]["bottom_centre"][0])
                    args["to"] = items[-1] if m_box.group(3) == "right" else items[0]
                elif re.search(r"\bpast (a|the)\b", clause) and prop:
                    px = self.results[prop]["bottom_centre"][0]
                    args["to"] = round(px + (2.2 if px >= here else -2.2), 2)
                elif prop:
                    args["to"] = prop
                elif re.search(r"\bback\b", clause):
                    args["to"] = round(start_x, 2)
                elif re.search(r"\baway\b|\boff\b", clause):
                    args["direction"] = "left" if "left" in clause else "right" if "right" in clause else (
                        last_dir or ("right" if here >= 0 else "left"))     # walks on the way it was going
                    args["distance"] = 4.0 if args["action"] == "run" else 2.5
                elif re.search(r"walks in", clause):
                    args["to"] = 0.0
                elif re.search(r"a few steps", clause):
                    args["cycles"] = 1.5
                    args["direction"] = "right" if here < 0 else "left"
                else:
                    if secs:
                        args["seconds"] = secs
                    elif re.search(r"to the (left|right) of the screen|across", clause):
                        args["to"] = round(-here * 0.9, 2)
                    else:
                        args["distance"] = 2.5
                    if "to" not in args:
                        args["direction"] = "left" if re.search(r"\bleft\b", clause) and not re.search(
                            r"from the left", clause) else "right" if re.search(r"\bright\b", clause) else (
                            "right" if here < 0 else "left")
                if "to" in args and isinstance(args["to"], str) and args["to"] == "it":
                    args["to"] = self._prop_any()
                r = self.call("play_action", **args)
                last_dir = r.get("facing") if r.get("facing") in ("left", "right") else last_dir
                here = r["end_x"]
                path.append((here, 1.7))
                last_target = args["to"] if isinstance(args.get("to"), str) else last_target
            else:
                args = {"name": name, "action": kind}
                if secs and kind in ("idle", "look_down", "wave"):
                    args["seconds"] = secs
                elif kind == "idle":
                    args["seconds"] = 2.5
                if kind == "react":
                    # a fright faces the scare; the figure then turns and gets away from it
                    nxt = events[events.index((kind, clause)) + 1:]
                    away = next((c for k, c in nxt if k == "walk"), "")
                    if re.search(r"\bright\b", away):
                        args["direction"] = "left"
                    elif re.search(r"\bleft\b", away):
                        args["direction"] = "right"
                if kind in ("look_down", "look"):
                    # "looks down at the ball" / "looks up at the tree" / "at it": look at that thing
                    at = re.search(r"\b(?:at|towards?) (?:a|the) (\w+)", clause)
                    thing = self._prop(at.group(1)) if at else (last_target if re.search(r"\bat it\b", clause) else None)
                    if thing:
                        args["to"] = thing
                    elif kind == "look":
                        args["direction"] = "right" if re.search(r"\bright\b", clause) else "left" if re.search(
                            r"\bleft\b", clause) else None
                        if not args["direction"]:
                            args.pop("direction")
                            args["action"] = "idle"            # "looks around" with nothing to look at
                            args["seconds"] = secs or 2.0
                if kind == "sit":
                    seat = re.search(r"\b(?:on|in) (?:a|the|it) ?(\w+)?", clause)
                    thing = self._prop(seat.group(1)) if seat and seat.group(1) else None
                    thing = thing or (last_target if last_target in self.results and
                                      last_target.rstrip("0123456789") in ("bench", "chair", "box") else None)
                    if thing:
                        args["to"] = thing
                    if re.search(r"facing (?:the )?(?:front|camera|us)", clause):
                        args["direction"] = "front"
                if kind == "turn":
                    if re.search(r"to face (?:the )?(?:front|camera|us)", clause):
                        args["direction"] = "front"
                    else:
                        d = re.search(r"\b(left|right)\b", clause)
                        args["direction"] = d.group(1) if d else "front"
                if kind == "pick_up":
                    m = re.search(r"\bup (?:a|the) (\w+)|\b(?:picks?|grabs?) (?:a|the) (\w+)", clause)
                    thing = self._prop(next(g for g in m.groups() if g)) if m else None
                    thing = thing or next((self._prop(s) for s in SHAPES if self._prop(s)), None)
                    if not thing:
                        continue
                    args["to"] = thing
                    if re.search(r"\bat (?:his|her|the) side\b|\bswing", clause):
                        args["carry"] = "swing"
                if kind == "put_down":
                    on = re.search(r"\b(?:on|onto|on top of) (?:a|the) (\w+)", clause)
                    thing = self._prop(on.group(1)) if on else None
                    if thing:
                        args["to"] = thing
                r = self.call("play_action", **args)
                if kind == "sit" and "to" in args:
                    last_target = args["to"]
        if r is None:
            r = self.call("play_action", name=name, action="idle", seconds=3)
        return self._end(r), path

    def _prop_any(self):
        return next(iter(self.results), None)
