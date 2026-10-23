"""Direct a clip from any request with any agent, and render it.

    python direct.py "a stick man walks to the table and waves"
    python direct.py --agent A2 --out outputs/direct/mine "a red ball bounces three times"

Agents: A0 template, A1 / A2 qwen via Ollama (P5_OLLAMA_URL for a remote server), A3 Claude via MCP.
Writes final.mp4, scene.blend and the tool-call log to the output folder.
"""
import argparse
import json
import re
import sys
import time

import config
from agent.claude_agent import ClaudeAgent
from agent.llm_agent import LLMAgent
from agent.template import Template
from blender_worker.client import BlenderWorker

AGENTS = {"A0": lambda: Template(), "A1": lambda: LLMAgent("qwen2.5:3b", "A1", fix_rounds=0),
          "A2": lambda: LLMAgent("qwen2.5:7b", "A2", fix_rounds=0), "A3": lambda: ClaudeAgent("A3", fix_rounds=0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("request")
    ap.add_argument("--agent", default="A3", choices=AGENTS)
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    slug = re.sub(r"[^a-z0-9]+", "_", a.request.lower()).strip("_")[:40]
    out = config.ROOT / (a.out or f"outputs/direct/{slug}_{a.agent}")
    log = []
    t = time.time()
    with BlenderWorker(out) as w:
        w.call("set_output", subdir="")
        stats = AGENTS[a.agent]().run(a.request, w, log=lambda tool, args, err: log.append(
            {"tool": tool, "args": args, **({"error": err} if err else {})}), task_id=None)
        print(f"{len(log)} tool calls in {time.time() - t:.0f} s")
        for c in log:
            print(" ", c["tool"], json.dumps(c["args"])[:160], ("ERROR " + c["error"][:100]) if c.get("error") else "")
        state = w.call("scene_state")
        print(f"clip: {state['frames']['seconds']} s")
        print(w.call("render_final", filename="final.mp4"))
        w.call("save_blend", filename="scene.blend")
    (out / "calls.json").write_text(json.dumps({"request": a.request, "agent": a.agent, "calls": log,
                                                "stats": {k: v for k, v in (stats or {}).items()
                                                          if k != "transcript"}}, indent=1, default=str),
                                    encoding="utf-8")


if __name__ == "__main__":
    main()
