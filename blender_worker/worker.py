"""Blender worker: runs inside headless Blender and executes tool calls sent over a local socket.

    blender -b --factory-startup --python blender_worker/worker.py -- --port 5123 --out outputs/run1

Protocol: one JSON object per line.
    request  {"id": 1, "tool": "add_primitive", "args": {...}}
    response {"id": 1, "ok": true, "result": {...}}  |  {"id": 1, "ok": false, "error": "..."}
"""
import argparse
import json
import os
import socket
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tools  # noqa: E402


def handle(req):
    name = req.get("tool")
    if name == "ping":
        return {"pong": True}
    fn = tools.TOOLS.get(name)
    if fn is None:
        raise tools.ToolError(f"unknown tool '{name}'")
    return fn(**req.get("args", {}))


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    tools.OUT_DIR = os.path.abspath(a.out)
    tools.scene_reset()

    srv = socket.create_server(("127.0.0.1", a.port))
    print(f"P5_WORKER_READY port={a.port}", flush=True)
    conn, _ = srv.accept()
    rf, wf = conn.makefile("r", encoding="utf-8"), conn.makefile("w", encoding="utf-8")
    for line in rf:
        if not line.strip():
            continue
        req = json.loads(line)
        if req.get("tool") == "shutdown":
            wf.write(json.dumps({"id": req.get("id"), "ok": True, "result": {}}) + "\n")
            wf.flush()
            break
        try:
            resp = {"ok": True, "result": handle(req)}
        except tools.ToolError as e:
            resp = {"ok": False, "error": str(e)}
        except Exception as e:  # a bug in a tool, not the agent's fault: keep the details for the log
            traceback.print_exc()
            resp = {"ok": False, "error": f"internal error in {req.get('tool')}: {type(e).__name__}: {e}",
                    "internal": True}
        resp["id"] = req.get("id")
        wf.write(json.dumps(resp) + "\n")
        wf.flush()
    conn.close()
    srv.close()


main()
