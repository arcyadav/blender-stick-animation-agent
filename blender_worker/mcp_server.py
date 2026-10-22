"""MCP server (stdio) offering the same validated tools to Claude (agent A3) or any MCP client.

    claude -p "..." --mcp-config mcp.json        # mcp.json: {"mcpServers": {"blender": {"command": "python",
                                                 #   "args": ["-m", "blender_worker.mcp_server"]}}}

Environment:
  P5_WORKER_PORT  attach to a running worker (the evaluation's), so the checker sees the same scene;
                  without it the server starts its own headless Blender (interactive use)
  P5_TASK         a task id from tasks.json: adds a `check_scene` tool returning the check report
                  (the fix loop: the agent checks, fixes, checks again)
  P5_LOG          a file to append every call and result to (JSON lines)

Plain JSON-RPC 2.0 over stdin/stdout, one message per line (no SDK needed).
"""
import json
import os
import sys
import time

import config
from blender_worker.client import BlenderWorker, ToolError
from blender_worker.schema import TOOLS, ValidationError, validate

PROTOCOL = "2025-06-18"
OFFERED = [t["function"] for t in TOOLS if t["function"]["name"] not in ("render_check", "render_final")]
CHECK_TOOL = {"name": "check_scene",
              "description": "Check the finished scene against the request (objects, positions, motion, "
                             "figures' actions, camera). Returns which checks fail and why. Call it when you "
                             "think you are done; fix what fails and check again (at most 3 fixes).",
              "parameters": {"type": "object", "properties": {}, "required": []}}


def _schema(s):
    """Our schemas carry a helper key ('oneOf_keys') that isn't JSON Schema; drop it for clients."""
    if isinstance(s, dict):
        return {k: _schema(v) for k, v in s.items() if k != "oneOf_keys"}
    if isinstance(s, list):
        return [_schema(v) for v in s]
    return s


class Server:
    def __init__(self):
        port = os.environ.get("P5_WORKER_PORT")
        self.w = BlenderWorker.attach(int(port)) if port else BlenderWorker(config.OUTPUTS / "mcp").start()
        self.task = self.defaults = None
        if os.environ.get("P5_TASK"):
            data = json.loads((config.ROOT / "tasks.json").read_text(encoding="utf-8"))
            self.task = next(t for t in data["tasks"] if t["id"] == os.environ["P5_TASK"])
            self.defaults = data["defaults"]["checks"]
        self.log_path = os.environ.get("P5_LOG")
        self.checks = 0

    def log(self, entry):
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": round(time.time(), 2), **entry}) + "\n")

    def tools(self):
        offered = OFFERED + ([CHECK_TOOL] if self.task else [])
        return [{"name": t["name"], "description": t["description"], "inputSchema": _schema(t["parameters"])}
                for t in offered]

    def call(self, name, args):
        if name == "check_scene" and self.task:
            from checks.checker import check_task, report_text
            self.checks += 1
            rep = check_task(self.task, self.w.call("sample_scene"), self.defaults)
            text = report_text(rep)
            self.log({"check": self.checks, "passed": rep["passed"], "report": text})
            if not rep["passed"] and self.checks > 3:
                text += "\n(No fixes left: this was the last check.)"
            return text, False
        try:
            clean, warns = validate(name, args)
        except ValidationError as e:
            self.log({"tool": name, "args": args, "invalid": str(e)})
            return f"ERROR (invalid call, nothing changed): {e}", True
        try:
            result = self.w.call(name, **clean)
        except ToolError as e:
            self.log({"tool": name, "args": args, "error": str(e)})
            return f"ERROR: {e}", True
        self.log({"tool": name, "args": args, "warnings": warns})
        return json.dumps(result, separators=(",", ":")), False

    def handle(self, msg):
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            ver = msg.get("params", {}).get("protocolVersion", PROTOCOL)
            return {"protocolVersion": ver, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "blender-stick-animation", "version": "0.3"},
                    "instructions": "Tools for a 2D stick-figure animation scene in Blender. Positions are "
                                    "[x, z] (z = height of the bottom); see each tool's description."}
        if method == "tools/list":
            return {"tools": self.tools()}
        if method == "tools/call":
            p = msg.get("params", {})
            text, err = self.call(p.get("name"), p.get("arguments") or {})
            return {"content": [{"type": "text", "text": text}], "isError": err}
        if method == "ping":
            return {}
        if mid is not None:
            raise KeyError(method)
        return None

    def serve(self):
        for line in sys.stdin:
            if not line.strip():
                continue
            msg = json.loads(line)
            if "id" not in msg:                 # a notification (e.g. notifications/initialized)
                continue
            try:
                out = {"jsonrpc": "2.0", "id": msg["id"], "result": self.handle(msg)}
            except KeyError as e:
                out = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"unknown method {e}"}}
            except Exception as e:  # never crash the client's session
                out = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(e)}}
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()
        self.w.close()


if __name__ == "__main__":
    Server().serve()
