"""Direct a story shot by shot, like a storyboard, in one continuous scene.

    python story.py stories/lost_ball.json
    python story.py stories/lost_ball.json --agent A3 --out outputs/story/lost_ball

A story file: {"title", "setting", "shots": ["...", ...], "camera": "..."}. Each shot is a short request
to the agent that continues the same scene (everything from earlier shots stays where it is) and starts
after the previous shot ends. The camera is set once, after the last shot. Renders final.mp4 (the whole
story), one check image per shot, scene.blend and a log of every call.
"""
import argparse
import json
import sys
import time

import config
from agent.claude_agent import ClaudeAgent
from agent.llm_agent import LLMAgent
from blender_worker.client import BlenderWorker

AGENTS = {"A1": lambda: LLMAgent("qwen2.5:3b", "A1", fix_rounds=0),
          "A2": lambda: LLMAgent("qwen2.5:7b", "A2", fix_rounds=0), "A3": lambda: ClaudeAgent("A3", fix_rounds=0)}


def _scene_summary(state):
    lines = []
    for o in state["objects"]:
        if o["kind"] == "ground":
            continue
        if o["kind"] == "figure":
            hold = f", holding {o['holding']}" if o.get("holding") else ""
            lines.append(f"- figure '{o['name']}' ({o.get('colour')}) at x {o['x_at_end']}, facing {o['facing_at_end']}"
                         f"{hold}; done so far: {', '.join(a['action'] for a in o['actions']) or 'nothing'}")
        else:
            lines.append(f"- {o['kind']} '{o['name']}' ({o.get('colour')}) at {o.get('bottom_centre')}, layer {o.get('layer')}")
    return "\n".join(lines) or "- nothing yet"


def shot_request(story, k, state):
    shots = story["shots"]
    done = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(shots[:k])) or "(none)"
    end = state["frames"]["end"]
    if k == 0:
        return (f"This is shot 1 of {len(shots)} of the story \"{story['title']}\". Setting: {story['setting']}\n"
                f"Make the setting, then only this shot: {shots[0]}\n"
                "Don't set the camera (it is framed after the last shot). Characters who appear in later shots "
                "can be added later.")
    return (f"This is shot {k + 1} of {len(shots)} of the story \"{story['title']}\". The scene is NOT empty: "
            f"earlier shots already happened and stay as they are:\n{done}\n\nIn the scene now (at the end of "
            f"shot {k}, frame {end}):\n{_scene_summary(state)}\n\n"
            f"Do only this shot: {shots[k]}\n"
            f"Start every action of this shot at frame {end + 1} or later (give start_frame to each figure's "
            "first action). Don't reset or re-add things, don't shorten the frame range, don't set the camera. "
            "Add new characters off-screen if they walk in.")


def camera_request(story, state):
    return (f"The story \"{story['title']}\" is animated (frames {state['frames']['start']}-{state['frames']['end']}). "
            f"In the scene:\n{_scene_summary(state)}\n\nNow only frame it with the camera: {story['camera']} "
            "Use set_camera and camera_move only; change nothing else.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("story")
    ap.add_argument("--agent", default="A3", choices=AGENTS)
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    story = json.loads((config.ROOT / a.story).read_text(encoding="utf-8"))
    out = config.ROOT / (a.out or f"outputs/story/{(config.ROOT / a.story).stem}_{a.agent}")
    agent = AGENTS[a.agent]()
    log, shots = [], []
    t0 = time.time()
    with BlenderWorker(out) as w:
        w.call("set_output", subdir="")
        w.call("scene_reset")
        for k in range(len(story["shots"]) + 1):
            state = w.call("scene_state")
            last = k == len(story["shots"])
            req = camera_request(story, state) if last else shot_request(story, k, state)
            start = state["frames"]["end"] if k else 1
            n0 = len(log)
            t = time.time()
            agent.run(req, w, log=lambda tool, args, err: log.append(
                {"shot": k + 1, "tool": tool, "args": args, **({"error": err} if err else {})}),
                task_id=f"shot{k + 1}", reset=False)
            after = w.call("scene_state")
            end = after["frames"]["end"]
            if k > 0:                   # characters new in this shot appear when the shot starts
                before = {o["name"] for o in state["objects"]}
                for o in after["objects"]:
                    if o["kind"] == "figure" and o["name"] not in before:
                        w.call("appear_at", name=o["name"], frame=start + 1)
            calls = log[n0:]
            errs = sum(1 for c in calls if c.get("error"))
            name = "camera" if last else f"shot {k + 1}"
            print(f"{name}: {len(calls)} calls, {errs} errors, {time.time() - t:.0f} s, frames {start}-{end}", flush=True)
            shots.append({"shot": name, "request": req, "frames": [start, end], "calls": len(calls), "errors": errs})
        state = w.call("scene_state")
        mids = [(s["frames"][0] + s["frames"][1]) // 2 for s in shots[:-1]]
        w.call("render_check", frames=mids[:8])
        print(w.call("render_final", filename="final.mp4"))
        w.call("save_blend", filename="scene.blend")
    print(f"story: {state['frames']['seconds']} s, {len(log)} calls, {time.time() - t0:.0f} s in all")
    (out / "story_log.json").write_text(json.dumps({"story": story, "agent": a.agent, "shots": shots, "calls": log},
                                                   indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
