"""Project-wide paths and constants."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"

# Blender 4.5 LTS, portable zip (pinned; see spec §3.5). Override with the BLENDER_EXE env var.
BLENDER_EXE = os.environ.get(
    "BLENDER_EXE", r"C:\Users\ysarc\tools\blender-4.5.14-windows-x64\blender.exe")

WORKER_SCRIPT = ROOT / "blender_worker" / "worker.py"
WORKER_START_TIMEOUT_S = 120
