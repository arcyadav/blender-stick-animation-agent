"""A3: Claude (Claude Code, `claude -p`) directs the scene through the same tools over MCP.

The MCP server attaches to the evaluation's Blender worker, so the checker sees Claude's scene.
Claude gets only these tools (built-in tools are off) and the same instructions as A1/A2; the fix
loop is a `check_scene` tool it calls when done (fix and check again, at most 3 fixes).
Runs on the user's Claude subscription: no API key, no per-token billing in this project.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import config
from agent.llm_agent import SYSTEM

PROMPT = """{system}

When the scene is finished, call check_scene. If checks fail, fix the scene with the tools and call \
check_scene again (at most 3 fixes). Then reply with a one-line summary.

Request: {request}"""


class ClaudeAgent:
    def __init__(self, name="A3", model=None, timeout=900, fix_rounds=3):
        self.name, self.model, self.timeout, self.fix_rounds = name, model, timeout, fix_rounds

    def run(self, request, w, log=None, check=None, task_id=None):
        w.call("scene_reset")
        work = Path(w.out_dir) / "claude_runs" / (task_id or "adhoc")
        work.mkdir(parents=True, exist_ok=True)
        calls_log = work / "mcp_calls.jsonl"
        calls_log.unlink(missing_ok=True)
        env_server = {"P5_WORKER_PORT": str(w.port), "P5_LOG": str(calls_log),
                      "PYTHONPATH": str(config.ROOT)}
        if task_id and self.fix_rounds:
            env_server["P5_TASK"] = task_id
        cfg = {"mcpServers": {"blender": {"command": sys.executable,
                                          "args": ["-m", "blender_worker.mcp_server"], "env": env_server}}}
        (work / "mcp.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        prompt = PROMPT.format(system=SYSTEM, request=request)
        if not (task_id and self.fix_rounds):
            prompt = prompt.replace("When the scene is finished, call check_scene. If checks fail, fix the scene "
                                    "with the tools and call check_scene again (at most 3 fixes). Then reply",
                                    "When the scene is finished, reply")
        cmd = ["claude", "-p", prompt, "--tools", "", "--mcp-config", str(work / "mcp.json"),
               "--strict-mcp-config", "--allowedTools", "mcp__blender", "--permission-mode", "dontAsk",
               "--output-format", "json", "--no-session-persistence"]
        if self.model:
            cmd += ["--model", self.model]
        t = time.time()
        # run outside the project folder so Claude sees nothing but the tools
        proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True, encoding="utf-8",
                              timeout=self.timeout, env={**os.environ, "PYTHONPATH": str(config.ROOT)})
        secs = time.time() - t
        out = {}
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            out = {"raw": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
        (work / "claude_output.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

        entries = [json.loads(x) for x in calls_log.read_text(encoding="utf-8").splitlines()] \
            if calls_log.exists() else []
        stats = {"tool_calls": 0, "invalid": 0, "tool_errors": 0, "warnings": 0, "rounds": [],
                 "llm_seconds": secs, "steps": out.get("num_turns"), "stopped": None,
                 "claude": {k: out.get(k) for k in ("num_turns", "duration_ms", "total_cost_usd", "usage",
                                                     "is_error", "result")}}
        for e in entries:
            if "check" in e:
                stats["rounds"].append({"passed": e["passed"], "report": e["report"], "tool_calls": stats["tool_calls"]})
                continue
            stats["tool_calls"] += 1
            stats["invalid"] += "invalid" in e
            stats["tool_errors"] += "error" in e
            stats["warnings"] += len(e.get("warnings") or [])
            if log:
                log(e["tool"], e["args"], e.get("invalid") or e.get("error"))
        if check is not None and (not stats["rounds"] or not stats["rounds"][-1]["passed"]):
            # Claude didn't check (or stopped on a failure): record where it ended up
            passed, report = check()
            if not stats["rounds"] or stats["rounds"][-1]["report"] != report:
                stats["rounds"].append({"passed": passed, "report": report, "tool_calls": stats["tool_calls"]})
        if proc.returncode != 0 and not entries:
            raise RuntimeError(f"claude exited with {proc.returncode}: {proc.stderr[-500:]}")
        return stats
