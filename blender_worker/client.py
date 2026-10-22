"""Starts a headless Blender worker and sends it tool calls (runs in normal Python, not Blender)."""
import json
import socket
import subprocess
import time
from pathlib import Path

import config


class ToolError(Exception):
    """The worker rejected a call (the message is meant for the agent)."""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BlenderWorker:
    def __init__(self, out_dir, blender=config.BLENDER_EXE):
        self.out_dir = Path(out_dir).resolve()
        self.blender = blender
        self.proc = self.sock = None
        self.port = None
        self._id = 0

    @classmethod
    def attach(cls, port, out_dir="."):
        """Connect to a worker someone else started (e.g. the evaluation), sharing its scene."""
        w = cls(out_dir)
        w.port = port
        w._connect(port, time.time() + 10)
        return w

    def _connect(self, port, deadline):
        while True:
            if self.proc is not None and self.proc.poll() is not None:
                raise RuntimeError(f"Blender exited during start-up; see {self.out_dir / 'blender.log'}")
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=1)
                break
            except OSError:
                if time.time() > deadline:
                    self.close()
                    raise RuntimeError("Blender worker did not start in time")
                time.sleep(0.3)
        self.sock.settimeout(None)
        self._r = self.sock.makefile("r", encoding="utf-8")
        self._w = self.sock.makefile("w", encoding="utf-8")

    def start(self):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        port = self.port = _free_port()
        self.log = open(self.out_dir / "blender.log", "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [self.blender, "-b", "--factory-startup", "--python", str(config.WORKER_SCRIPT),
             "--", "--port", str(port), "--out", str(self.out_dir)],
            stdout=self.log, stderr=subprocess.STDOUT)
        self._connect(port, time.time() + config.WORKER_START_TIMEOUT_S)
        return self

    def call(self, tool, **args):
        """Run one tool; returns its result dict or raises ToolError with the worker's message."""
        self._id += 1
        self._w.write(json.dumps({"id": self._id, "tool": tool, "args": args}) + "\n")
        self._w.flush()
        line = self._r.readline()
        if not line:
            raise RuntimeError(f"Blender worker died; see {self.out_dir / 'blender.log'}")
        resp = json.loads(line)
        if not resp["ok"]:
            raise ToolError(resp["error"])
        return resp["result"]

    def close(self):
        if self.sock:
            if self.proc:                          # our own worker: stop it; an attached one keeps running
                try:
                    self.call("shutdown")
                except Exception:
                    pass
            self.sock.close()
            self.sock = None
        if self.proc:
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if getattr(self, "log", None):
            self.log.close()

    def __enter__(self):
        try:
            return self.start()
        except RuntimeError:                       # a rare start-up race on Windows: try once more
            self.close()
            return self.start()

    def __exit__(self, *exc):
        self.close()
