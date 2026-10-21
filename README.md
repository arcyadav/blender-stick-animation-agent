# Blender Stick-Animation Agent (UMC301 Project 5)

Type what should happen ("a stick man walks to the table and waves"). An agent builds the scene in
**Blender** through a small set of validated tools, checks the result from the scene data, fixes what
fails, and renders an MP4 plus an editable `.blend` file. Different LLMs are compared on the same 30 tasks.

- **Spec** (plan, design, status as built): `Project-5-spec.md`
- **Task set:** `tasks.json` (30 requests with machine-checkable checks)

## Setup
- Blender **4.5 LTS** (portable zip). Path in `config.py`, or set `BLENDER_EXE`.
- Python 3.11 (no extra packages needed yet).
- Ollama with `qwen2.5:3b` and `qwen2.5:7b` for the local agents.

## Run
```powershell
python eval.py --agent A0 --category static_layout,object_motion          # template baseline + checks
python eval.py --agent A0 --ids m01 --render                              # + check frames, MP4, .blend
python -m scripts.demo_bounce                                             # a bouncing ball, tool by tool
python -m tests.test_schema; python -m tests.test_placement; python -m tests.test_checker
```
Results go to `outputs/` (not in git): `outputs/eval/<agent>/<task>/result.json`, renders, `scene.blend`.

## Layout
```
blender_worker/  worker.py (runs inside headless Blender), client.py, tools.py (bpy), schema.py (tool defs + validation)
checks/          checker.py (scene checks from sampled frames), figure_checks.py
agent/           template.py (A0 baseline); LLM agents next
scripts/         demos
tests/           validation, placement, checker (broken scenes must fail)
eval.py          run an agent on tasks.json and check every result
```
