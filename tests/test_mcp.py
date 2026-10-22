"""The MCP server speaks JSON-RPC over stdio and drives the evaluation's worker.  python -m tests.test_mcp"""
import json
import os
import subprocess
import sys

import config
from blender_worker.client import BlenderWorker


def main():
    with BlenderWorker(config.OUTPUTS / "test_mcp") as w:
        w.call("scene_reset")
        env = {**os.environ, "P5_WORKER_PORT": str(w.port), "P5_TASK": "s02", "PYTHONPATH": str(config.ROOT)}
        srv = subprocess.Popen([sys.executable, "-m", "blender_worker.mcp_server"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env, cwd=config.ROOT)

        def rpc(i, method, params=None):
            srv.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}) + "\n")
            srv.stdin.flush()
            return json.loads(srv.stdout.readline())

        init = rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "0"}})
        assert init["result"]["capabilities"] == {"tools": {}}, init
        srv.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        names = [t["name"] for t in rpc(2, "tools/list")["result"]["tools"]]
        assert "play_action" in names and "check_scene" in names and "render_final" not in names, names
        bad = rpc(3, "tools/call", {"name": "add_primitive", "arguments": {"type": "pyramid", "name": "p"}})
        assert bad["result"]["isError"] and "must be one of" in bad["result"]["content"][0]["text"], bad
        for i, (name, args) in enumerate([
                ("add_asset", {"asset": "table", "name": "table", "location": [0, 0]}),
                ("add_primitive", {"type": "sphere", "name": "ball", "location": {"on_top_of": "table"},
                                   "size": 0.18, "colour": "red"})]):
            r = rpc(10 + i, "tools/call", {"name": name, "arguments": args})
            assert not r["result"]["isError"], r
        first = rpc(20, "tools/call", {"name": "check_scene", "arguments": {}})["result"]["content"][0]["text"]
        print("check before the chair:", first.splitlines()[0])
        rpc(21, "tools/call", {"name": "add_asset", "arguments": {"asset": "chair", "name": "chair",
                                                                  "location": {"next_to": "table"}}})
        second = rpc(22, "tools/call", {"name": "check_scene", "arguments": {}})["result"]["content"][0]["text"]
        print("check after:", second.splitlines()[0])
        srv.stdin.close()
        srv.wait(timeout=20)
        # the evaluation's own connection still sees the scene the MCP client built
        names = [o["name"] for o in w.call("scene_state")["objects"]]
        assert names == ["ground", "table", "ball", "chair"], names
        assert "fail" in first and second.startswith("All"), (first, second)
    print("all MCP tests passed")


if __name__ == "__main__":
    main()
