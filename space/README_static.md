---
title: Stick Animation Agent
emoji: 🎬
colorFrom: red
colorTo: blue
sdk: static
app_file: index.html
pinned: false
short_description: An AI agent directs stick-figure animation in Blender
---

# Stick Animation Agent (UMC301 Project 5)

An agent directs a 2D stick-figure scene in Blender through ~16 checked tools, checks the result from the
scene data, fixes what fails and renders the clip. Four directors on the same 30 tasks: template rules,
qwen2.5 3b, qwen2.5 7b and Claude via MCP.

This page has the two stories, the action library, and every final run (tool calls, checks, clip).
Live directing runs locally: `python demo_app.py`.

Code: https://github.com/arcyadav/blender-stick-animation-agent
