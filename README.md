# Blender Stick-Animation Agent (UMC301 Project 5)

Type what should happen ("a stick man walks to the table and waves"). An agent builds the scene in
**Blender** through a small set of validated tools, checks the result from the scene data, fixes what
fails, and renders an MP4 plus an editable `.blend` file. Different LLMs are compared on the same 30 tasks.

The world is **2D**, like paper: flat colours, white background, a black ground line, an orthographic side
camera. Stick figures play a motion library (Project 3 walks and a wave from my own video) with planted feet,
smooth blends and turns.

- **Spec** (plan, design, status as built): `Project-5-spec.md`
- **Task set:** `tasks.json` (30 requests with machine-checkable checks)

## Setup
- Blender **4.5 LTS** (portable zip). Path in `config.py`, or set `BLENDER_EXE`.
- Python 3.11 (no extra packages needed yet). FFmpeg only for `scripts/sheet.py`.
- Ollama with `qwen2.5:3b` and `qwen2.5:7b` for the local agents.

## Run
```powershell
python eval.py --agent A0 --category static_layout,object_motion          # template baseline + checks
python eval.py --agent A0 --ids m01 --render                              # + check frames, MP4, .blend
python eval.py --agent A3                                                 # Claude via MCP (claude -p, subscription)
$env:P5_OLLAMA_URL="https://…"; python eval.py --agent A2                 # qwen via Ollama (local, or a Kaggle GPU:
                                                                          #   kaggle/ollama_gpu_server.ipynb)
python -m scripts.results                                                 # comparison tables (markdown)
python -m scripts.demo_figure                                             # a stick man walks to the table and waves
python -m scripts.demo_bounce                                             # a bouncing ball, tool by tool
python -m scripts.sheet outputs/eval/A0/p04/final.mp4                     # contact sheet of a clip
python -m tests.test_schema; python -m tests.test_placement; python -m tests.test_checker
python -m tests.test_figure_checks                                        # no Blender needed
python -m tests.test_mcp
```
Results go to `outputs/` (not in git): `outputs/eval/<agent>/<task>/result.json`, renders, `scene.blend`.

## Layout
```
blender_worker/  worker.py (runs inside headless Blender), client.py, tools.py (bpy), schema.py (tool defs + validation),
                 motion.py (stick-figure motion: poses, library clips, timeline, blends; plain Python)
motions/         motion library copied from Project 3 (walks, wave)
checks/          checker.py (scene checks from sampled frames), figure_checks.py (feet, pops, actions, targets)
agent/           template.py (A0 baseline), llm_agent.py (A1/A2, Ollama), claude_agent.py (A3, claude -p + MCP)
blender_worker/mcp_server.py  the same tools as an MCP server (attaches to a running worker)
kaggle/          notebook: Ollama on a Kaggle GPU behind a tunnel
scripts/         demos
tests/           validation, placement, checker (broken scenes must fail)
eval.py          run an agent on tasks.json and check every result
```
