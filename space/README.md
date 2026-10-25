---
title: Stick Animation Agent
emoji: 🎬
colorFrom: red
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: An AI agent directs stick-figure animation in Blender
---

# Stick Animation Agent (UMC301 Project 5)

Type what should happen; an agent directs a 2D stick-figure scene in Blender through ~16 checked tools,
checks the result from the scene data, and renders the clip.

- **Direct**: the template rules (A0) direct your request live; Blender renders it on this server's CPU.
- **Task + checks**: run one of the 30 evaluation tasks and see every check.
- **Results**: the final run of all four agents (template rules, qwen2.5 3b, qwen2.5 7b, Claude via MCP)
  on the same 30 tasks: tool calls, checks, and each clip rebuilt from the agent's own calls.

Claude (A3) and qwen (A1/A2) direct live in the local demo (`python demo_app.py`), since Claude runs on
the author's subscription and qwen on a Kaggle GPU.

Code: https://github.com/arcyadav/blender-stick-animation-agent
