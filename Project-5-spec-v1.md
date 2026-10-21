# Spec — An AI Agent That Uses Blender as a Tool (UMC301 Project 5)

Author: Archana Yadav
Duration: 2–3 working days (only if Projects 3 and 4 are submittable by ~24 Oct 2026; deadline 27 Oct 2026, 2 pm)
Status: Draft v1

---

## 1. Problem
Professional creative software (Blender, OpenToonz, Photoshop) is powerful but needs a skilled human to drive
it. Generative AI skips the software and produces pixels directly, which gives no control, no editable result
and no consistency (the drift problem from Project 3). A middle way: an **AI agent that operates the real
software through tools**. The result is a real, editable Blender scene, and the agent can check its own output
and fix it.

## 2. Goal
Build an agent that turns a plain-language request into a **short animated Blender scene**, using a small,
safe set of Blender tools. It renders, checks the result, and corrects itself. Then evaluate how reliably
different LLMs use the tools.

```
"a red ball bounces three times on a wooden table, the camera slowly orbits"
  → plan → tool calls (add table, add ball, material, keyframes, camera orbit, light)
  → render key frames → checks (ball visible? touches the table 3 times? inside frame?)
  → fix (e.g. move the camera back) → final MP4 + the .blend file
```

**Research question:** *How reliably can LLMs of different sizes operate professional software through tools,
and how much do scene-state feedback and a self-check loop help?*

---

## 3. What Blender can do (background, so we don't proceed on half knowledge)

Blender is free and open source (GPL), runs on Windows/Linux/macOS, and **everything in it is scriptable
in Python** (`bpy`). That makes it the best "software as a tool" target.

### 3.1 Ways to control Blender from code
| Way | How | Use in this project |
|---|---|---|
| **Headless / background mode** | `blender -b scene.blend --python script.py` runs a script with no window; `-f 1` renders one frame, `-a` the animation | **Main mode**: a Blender worker process the agent sends commands to |
| **Python API (`bpy`)** | `bpy.ops` (operators, as in the UI), `bpy.data` (direct data access: objects, materials, actions), `bpy.context` | Tools are written against `bpy.data` (stable, no UI context needed) |
| **Add-on with a socket server** | a small add-on inside a running Blender listens on a local port, receives JSON commands | Optional: live view while the agent works (the approach of the open-source *BlenderMCP* project) |
| **`bpy` as a pip module** | `pip install bpy` (tied to one Python version, large) | Not used: version pinning pain on Windows |

### 3.2 What can be built and animated
| Area | Capabilities | In scope? |
|---|---|---|
| Objects | primitives (cube, sphere, cylinder, plane, cone, torus, monkey), text, curves, imported models | ✅ primitives + a small asset library |
| Import/export | glTF/GLB, FBX (e.g. Mixamo characters with animations), OBJ, STL, images as planes | ✅ glTF assets (CC0, e.g. Poly Haven), images as planes |
| Materials | Principled BSDF (colour, roughness, metallic, emission, transparency), image textures, node shaders | ✅ colour / roughness / metallic / emission presets |
| Lights / world | sun, point, spot, area lights; world colour or HDRI environment | ✅ 3-point preset + sun + HDRI |
| Camera | perspective/orthographic, focal length, depth of field, Track-To constraint, follow path | ✅ placement, look-at, orbit, dolly, follow |
| **Animation** | keyframes on any property (`keyframe_insert`), F-curve interpolation (Bezier, linear, constant, bounce/elastic easing), NLA strips, drivers, constraints | ✅ keyframes + easing (the core of the project) |
| Rigging | armatures/bones, IK, weight painting, shape keys | ⚠ only for imported rigged characters (play / retime their actions) |
| Physics | rigid body, cloth, soft body, fluid, particles; must be baked | ⚠ stretch: rigid-body drop/collide only |
| Procedural | Geometry Nodes (scatter, arrays, procedural shapes) | ❌ out of scope (too open-ended) |
| **2D** | **Grease Pencil**: 2D drawing + frame-by-frame or rigged 2D animation inside 3D | ⚠ stretch: Project 3 character parts as image planes (2.5D cut-out) |
| Video editing | Video Sequence Editor: cut clips, add audio/text | ❌ |

### 3.3 Rendering (speed matters on a laptop)
| Engine | Look | Speed | Notes |
|---|---|---|---|
| **Workbench** | flat/solid, no real lighting | fastest (≪1 s/frame) | always works; used for **check renders** |
| **EEVEE** | real-time, good lighting, shadows | ~0.2–2 s/frame | needs a working OpenGL GPU driver (integrated GPUs usually OK) — **verify on Day 1** |
| Cycles | path-traced, photoreal | slow on CPU (10 s–minutes/frame) | ❌ except a single "hero" still |

Output: PNG frames or MP4 (FFmpeg built in). Plan: 3–6 s clips, 24 fps, 960×540 for checks, 1280×720 final.

### 3.4 Limits to know
- `bpy.ops` operators often need a UI context (an area/window). In background mode, prefer `bpy.data` + low-level calls.
- The API changes between major versions (e.g. 2.7x → 2.8, 4.x → 5.x). Pin one version and record it.
- EEVEE in background mode can fail without a GPU. Workbench is the fallback.
- Blender has no "understanding": it will happily render an empty frame or an object behind the camera.
  That's exactly why the agent needs checks.

---

## 4. What we will build

### 4.1 Architecture
```
request ──► Agent (LLM, tool calling loop)
              │  tool calls (JSON)          ▲ results + scene state (JSON) + check reports
              ▼                             │
         Tool layer (validated, ~14 tools)  │
              │                             │
         Blender worker (headless, bpy) ────┘ ──► .blend + check renders + final MP4
              │
         Checker: geometric checks (from the scene data) + optional VLM yes/no questions on renders
```
- The agent **never runs free-form Python**: only the listed tools, with validated arguments (safety, and
  measurable tool use).
- After each step the tool layer returns a compact **scene state** (objects, positions, sizes, keyframes,
  camera), so the LLM "sees" the scene as data.

### 4.2 Tools (v1)
| Tool | Arguments (validated) |
|---|---|
| `scene_reset` | — |
| `scene_state` | — → objects, bounds, materials, keyframes, camera, frame range |
| `add_primitive` | type ∈ {cube, sphere, cylinder, plane, cone, torus}, name, location, size |
| `add_asset` | asset ∈ local library (table, chair, tree, lamp, …, ~15 CC0 glTF), name, location, scale |
| `set_transform` | name, location / rotation / scale |
| `set_material` | name, colour, preset ∈ {matte, plastic, metal, glass, glow, wood} |
| `add_light` | type ∈ {sun, point, area}, preset ∈ {day, studio, sunset, night}, location |
| `set_camera` | location, look_at (object or point), focal length |
| `camera_move` | kind ∈ {orbit, dolly_in, dolly_out, follow, pan}, target, start/end frame |
| `keyframe` | name, property ∈ {location, rotation, scale, colour}, frame, value |
| `set_easing` | name, property, interpolation ∈ {linear, ease_in_out, bounce, elastic, constant} |
| `set_frames` | start, end, fps |
| `render_check` | frames (list) → Workbench PNGs + check report |
| `render_final` | → MP4 (EEVEE, else Workbench) |

Stretch tools: `add_rigid_body` (drop/collide, baked), `play_action` (an imported rigged character's walk),
`image_plane` (Project 3 character parts → 2.5D cut-out).

### 4.3 Self-check (the agent's critic)
**Geometric checks** (exact, from scene data, no AI needed):
- every requested object exists, sits **inside the camera view** (projected bounding box), is not hidden behind another object
- objects rest **on** a surface (no floating, no intersections; bounding-box tests)
- motion matches the request: counted bounces (local minima of height touching the surface), direction,
  start/end positions, duration
- the camera isn't inside an object; the light isn't zero

**Visual check (optional):** a small local VLM (via Ollama, e.g. `qwen2.5vl:3b`) answers 3–5 yes/no
questions on the check renders ("Is there a red ball on a table?"). One vote, never the only check (as in
Project 3).

Failure → the report goes back to the agent → it fixes with tools (max 3 rounds), and every decision is logged.

### 4.4 Agents compared
| ID | Brain | Cost |
|---|---|---|
| A1 | `qwen2.5:3b` via Ollama (tool calling) | free, laptop |
| A2 | `qwen2.5:7b` via Ollama | free, laptop (slower) |
| A3 | Claude (Claude Code via an MCP server exposing the same tools) | existing subscription, no API spend |
| A0 | template baseline: rules → fixed tool sequence | free |

Same tools and checks for all, so the comparison is fair.

---

## 5. Evaluation
**Task set (~30 requests, written before building, each with a machine-checkable spec):**
- static layout (8): "three cubes in a row, the middle one blue"
- motion (10): "the ball bounces 3 times", "the cube spins once in 2 s"
- camera (6): "orbit around the table", "the camera follows the car"
- multi-step / relational (6): "a lamp on the table, the ball rolls off the table and lands next to the chair"

**Metrics:** task success (all checks pass); per-check pass rate; valid tool-call rate (schema-valid,
correct names); steps and fix rounds; time per task; VLM check agreement with the geometric checks.

**Studies:**
1. Model: A0 vs A1 vs A2 vs A3
2. Scene-state feedback on/off (does seeing the scene as data help?)
3. Self-check loop on/off (success before vs after fixes)
4. Failure analysis: wrong coordinates, forgotten objects, wrong easing, camera misses

Human check: rate 10 final clips (does it match the request? 1–5) against the automatic score.

---

## 6. Deliverables
- `blender_worker/` (headless worker + tools), `agent/` (loop, prompts, backends), `checks/`, `tasks.json`, `eval.py`
- MCP server exposing the tools (used by the Claude backend; also lets anyone drive Blender from Claude)
- Results tables + clips; report
- **Deployment:** a static showcase page (requests → clips, results, failure gallery) on a free static Hugging Face Space;
  live demo from the laptop (needs Blender installed) via a Gradio share link, as in Project 3
- Transcript of the Claude Code session → HTML (Turn 1, 2, … collapsed)

## 7. Timeline (3 days)
| Day | Work |
|---|---|
| 0 (½ h) | **Verify:** Blender installed (record the version), headless render works, EEVEE works or Workbench fallback, Ollama tool calling works with qwen2.5 |
| 1 | worker + 14 tools + scene state; template baseline A0; 30-task set with specs; geometric checks |
| 2 | agent loop (A1/A2), self-check + fix loop, MCP server + A3; run the evaluation |
| 3 | studies + tables, showcase page + deploy, report, transcript |

## 8. Risks
| Risk | Mitigation |
|---|---|
| EEVEE fails headless on the laptop | Workbench for everything (clean flat look) |
| Small LLMs give bad tool calls / coordinates | validated schemas, error messages returned to the model, scene state, a "place relative to object" helper (`on_top_of`, `next_to`) so the model needn't do maths |
| Blender API differences | pin one version, use `bpy.data` not `bpy.ops` |
| Scope creep (physics, characters, geometry nodes) | v1 = primitives + assets + keyframes + camera; the rest are stretch tools only |
| Time (3 projects, one deadline) | start only if P3 + P4 are submittable; cut studies 2–4 before cutting the core |

## 9. Out of scope
Modelling new objects from scratch, character rigging, photoreal Cycles renders, free-form code execution,
Geometry Nodes, long films.

## 10. Acceptance criteria
- The agent completes ≥ 60% of the 30 tasks end to end with at least one backend, with results reported for all
- Self-check loop measured (success before vs after fixes)
- Deployed showcase URL; report + transcript submitted before 27 Oct 2026, 2 pm

## 11. Related work (to read and cite — check exact details before citing)
- **BlenderMCP** (open source, 2025): connects Claude to Blender via MCP with an add-on socket server
- **3D-GPT** (2023): LLM agents generating 3D scenes through procedural Blender code
- **SceneCraft** (2024): LLM agent that writes Blender scripts and refines them with a vision model critic
- **BlenderAlchemy** (2024): vision-language model edits Blender materials/scenes iteratively
- **Toolformer** (2023), **ReAct** (2022): language models that use tools / reason-act loops
- Model Context Protocol (Anthropic, 2024): the standard for exposing tools to LLMs
