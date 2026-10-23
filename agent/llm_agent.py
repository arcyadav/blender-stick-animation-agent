"""A1 / A2: an LLM (qwen2.5 via Ollama) directs the scene through the validated tools.

Loop: the model calls tools (validated outside Blender; bad calls come back as error text it can act
on) until it answers without a tool call. Then the checker runs; if checks fail, the report goes back
as a new message and the model fixes the scene (up to `fix_rounds` times). Everything is logged.
"""
import json
import os
import time
import urllib.error
import urllib.request

from blender_worker.client import ToolError
from blender_worker.schema import TOOLS, ValidationError, validate

# P5_OLLAMA_URL: another Ollama server (e.g. a Kaggle GPU behind a tunnel), else the local one
OLLAMA = os.environ.get("P5_OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/chat"
VERBOSE = bool(os.environ.get("P5_VERBOSE"))
# renders are made by the evaluation, not the agent (it can't see images)
OFFERED = [t for t in TOOLS if t["function"]["name"] not in ("render_check", "render_final")]

SYSTEM = """You direct a short 2D animation in Blender by calling tools. The scene is already empty and ready (ground line at z = 0, white background, 24 fps). Make exactly what the request asks for: no extra objects, no stick figures unless the request has one.

The world is 2D, seen from the side like paper:
- positions are [x, z]: x = left/right (screen-left is negative, about -4 to 4 is on screen), z = height of the object's BOTTOM (0 = standing on the ground). Or use a placement: {"on_top_of": "table"}, {"next_to": "table", "side": "left"}.
- props (table, chair, bench, box, lamp, tree) come from add_asset; shapes (ball = sphere, cube, cone, ...) from add_primitive. Depth is only a layer: "back", "middle" (default) or "front".
- if the request has a stick figure: add_stick_figure, then one play_action per action, in order (walk, walk_happy, walk_sad, walk_worried, run, wave, idle, look, look_down, react, sigh, handshake, pick_up, put_down, sit, stand_up, turn). Walks take `to` (an object's name: it stops beside it) or `distance` / `seconds` with `direction`. look_down takes `to` = what to look at; pick_up `to` = a small object (walk to it first); put_down `to` = a surface or the ground. Figures are animated only with play_action. Put props a figure walks past in the back layer.
- moving objects: keyframe (location, rotation, scale, colour) at frames, then set_easing (gravity for bounces and falls), and set_frames to cover the motion.
- a figure that "walks in" or "comes in" starts just off-screen (beyond the camera's shows_x) and walks into view.
- small props read better a little bigger than life (a phone about 0.3 m, a cup 0.25 m), like cartoons.
- camera: set_camera(look_at, width) frames the shot; camera_move does pan / zoom_in / zoom_out / follow.

Make the objects, animate them, then frame the camera so everything is in view. When the scene is finished, reply with a short summary and no tool call."""

FIX = """The scene was checked against the request. {report}
Fix the scene with tools (objects and figures you made are still there; scene_state shows them). \
When done, reply with a short summary and no tool call."""


MAX_REPLY_TOKENS = 1500       # a reply longer than this is a model rambling in a loop


def _chat(model, messages, timeout=600, tries=3):
    """One model turn. Streamed, so a slow reply keeps the connection busy (a Cloudflare tunnel cuts
    requests that are silent for 100 s); retried on network errors."""
    body = {"model": model, "messages": messages, "tools": OFFERED, "stream": True, "keep_alive": "60m",
            "options": {"temperature": 0, "num_ctx": 8192, "seed": 0, "num_predict": MAX_REPLY_TOKENS}}
    data = json.dumps(body).encode()
    for attempt in range(tries):
        try:
            req = urllib.request.Request(OLLAMA, data=data, headers={"Content-Type": "application/json"})
            msg = {"role": "assistant", "content": ""}
            calls = []
            with urllib.request.urlopen(req, timeout=timeout) as r:
                for line in r:
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise RuntimeError(f"Ollama: {chunk['error']}")
                    m = chunk.get("message", {})
                    msg["content"] += m.get("content", "")
                    calls += m.get("tool_calls") or []
                    if chunk.get("done"):
                        break
            if calls:
                msg["tool_calls"] = calls
            return {"message": msg}
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def _compact(result, limit=1200):
    s = json.dumps(result, separators=(",", ":"))
    return s if len(s) <= limit else s[:limit] + "…"


class LLMAgent:
    def __init__(self, model, name, max_steps=40, fix_rounds=3):
        self.model, self.name, self.max_steps, self.fix_rounds = model, name, max_steps, fix_rounds

    def run(self, request, w, log=None, check=None, task_id=None, reset=True):
        """check(): → (passed, report_text); called when the model says it is done."""
        stats = {"tool_calls": 0, "invalid": 0, "tool_errors": 0, "warnings": 0, "rounds": [],
                 "llm_seconds": 0.0, "steps": 0, "stopped": None}
        if reset:
            w.call("scene_reset")
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": request}]
        for rnd in range(self.fix_rounds + 1):
            self._loop(messages, w, log, stats)
            if check is None:
                break
            passed, report = check()
            stats["rounds"].append({"passed": passed, "report": report, "tool_calls": stats["tool_calls"]})
            if passed or rnd == self.fix_rounds or stats["stopped"] == "max_steps":
                break
            messages.append({"role": "user", "content": FIX.format(report=report)})
        stats["transcript"] = messages
        return stats

    def _loop(self, messages, w, log, stats):
        repeats = {}
        for _ in range(self.max_steps):
            if stats["steps"] >= self.max_steps * 2:
                stats["stopped"] = "max_steps"
                return
            t = time.time()
            msg = _chat(self.model, messages)["message"]
            stats["llm_seconds"] += time.time() - t
            if VERBOSE:
                print(f"  [{self.name} {time.time() - t:5.1f}s] {(msg.get('content') or '')[:120]!r}", flush=True)
            stats["steps"] += 1
            calls = msg.get("tool_calls") or []
            messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
            if not calls:
                return
            for c in calls:
                fn = c.get("function", {})
                name, args = fn.get("name", ""), fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"_unparsed": args}
                stats["tool_calls"] += 1
                key = json.dumps([name, args], sort_keys=True)
                if repeats.get(key, 0) >= 2:
                    # small models loop on one call (36 identical set_camera calls were seen); only calls
                    # that worked count, so a failing call keeps getting its real error message
                    stats["repeats"] = stats.get("repeats", 0) + 1
                    content = (f"ERROR: this exact {name} call already succeeded {repeats[key]} times, so it is "
                               "done. Do the next step, or reply with a short summary if the scene is finished.")
                    if log:
                        log(name, args, content)
                    messages.append({"role": "tool", "content": content, "tool_name": name})
                    continue
                try:
                    clean, warns = validate(name, args)
                    stats["warnings"] += len(warns)
                    result = w.call(name, **clean)
                    content = _compact(result)
                    ok = True
                    repeats[key] = repeats.get(key, 0) + 1
                except ValidationError as e:
                    stats["invalid"] += 1
                    content, ok = f"ERROR (invalid call, nothing changed): {e}", False
                except ToolError as e:
                    stats["tool_errors"] += 1
                    content, ok = f"ERROR: {e}", False
                if log:
                    log(name, args, content if not ok else None)
                if VERBOSE:
                    print(f"    {name} {json.dumps(args)[:150]} -> {content[:150]}", flush=True)
                messages.append({"role": "tool", "content": content, "tool_name": name})
        stats["stopped"] = "max_steps"
