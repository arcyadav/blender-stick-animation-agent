# Spec — An Agent That Directs Stick-Figure Animation in Blender (UMC301 Project 5)

Author: Archana Yadav
Duration: 21–27 Oct 2026 (deadline 27 Oct 2026, 2 pm). Projects 3 and 4 are done.
Status: Draft v2 (v1 kept as `Project-5-spec-v1.md`)

---

## 0. The story (why this project, after Project 3)
- **Project 3** went straight for the hard version: a drawn character from a character sheet, cut into parts,
  driven by a motion library. The **motion transferred** to a second character with zero new animation work, but
  **appearance broke**: cutting flat drawings into parts needed colour rules tuned to one character (dark tee →
  invisible sleeve seam → torso looks cut apart; see P3 `docs/reuse_test.md`).
- **Lesson:** motion and appearance are separate problems, and appearance is the hard one.
- **Project 5** separates them. Appearance and rendering come from **real professional software (Blender)**,
  the characters are **stick figures** so only the motion matters, and an **AI agent directs the scene** through tools.
- This is also how animators are trained: *The Animator's Survival Kit* (R. Williams) starts with the bouncing
  ball, then a simple figure, then the walk, and animators block shots with simple rigs before final art.
  Our task set follows the same ladder.

## 1. Problem
Professional creative software (Blender) is powerful but needs a skilled human to drive it. Generative video
skips the software and gives no control, no editable result and drift (Project 3). A middle way: an **AI agent
that operates the real software through tools**. The result is a real, editable `.blend` scene, and the agent
can check its own output and fix it.

## 2. Goal
Build an agent that turns a plain-language request into a **short stick-figure animation in Blender**
(5–15 s, 1–2 figures, a few props, a camera), using a small, safe set of tools. It renders, checks and
corrects itself. Then evaluate how reliably different LLMs direct it.

```
"a stick man walks to the table, sees the ball, steps back and waves"
  → plan → tool calls (table, ball, stick figure, walk → stop → react → wave, side camera, light)
  → check (feet planted? reaches the table? no pops between actions? in frame? actions in order?)
  → fix (e.g. one more walk cycle, move the camera back) → final MP4 + the .blend file
```

**Research question:** *How reliably can LLMs of different sizes direct animation in professional software
through tools, and how much do scene-state feedback and a self-check loop help?*

**What "good" means here:** grounded (no foot slide or float), smooth (no pops between actions), timed
(ease in/out, holds), readable staging (camera suits the action), and the requested story beats in order.
Target quality: clean animation blocking, not finished film.

---

## 3. What Blender can do (background)
Blender is free and open source (GPL), runs on Windows, and **everything is scriptable in Python** (`bpy`).

### 3.1 Ways to control Blender from code
| Way | How | Use here |
|---|---|---|
| **Headless mode** | `blender -b --python worker.py`; `-f 1` one frame, `-a` animation | **Main**: a worker process the agent sends commands to |
| **Python API** | `bpy.data` (direct data), `bpy.ops` (UI operators), `bpy.context` | tools use `bpy.data` (no UI context needed) |
| Add-on socket server | add-on in a running Blender receives JSON (as in *BlenderMCP*) | optional live view |
| `bpy` pip module | tied to one Python version, large | not used |

### 3.2 What can be built and animated
| Area | In scope? |
|---|---|
| Primitives (cube, sphere, cylinder, plane, cone, torus) | ✅ |
| Props | ✅ 6 props (table, chair, bench, box, lamp, tree) **built from primitives** instead of CC0 glTF: one flat style with the stick figures, no download/cleanup, and an exact support height (`top_z`) for things that hold others |
| Materials (Principled BSDF presets) | ✅ |
| Lights, world colour | ✅ presets |
| Camera (placement, look-at, orbit, dolly, follow) | ✅ |
| Keyframes + F-curve interpolation | ✅ core |
| **Stick figures** (joints + bones driven by a motion library) | ✅ **core** |
| Armatures / IK, real 3D rigs | ⚠ stretch (3D stick armature) |
| Physics (rigid body) | ❌ |
| Geometry Nodes, Grease Pencil, Video Sequence Editor | ❌ |

### 3.3 Rendering
| Engine | Speed | Use |
|---|---|---|
| **Workbench** | ≪1 s/frame | check renders; fallback for everything |
| **EEVEE** | ~0.2–2 s/frame | final clips if it works headless on the laptop (**verify Day 0**) |
| Cycles | slow on CPU | ❌ |

Check renders 960×540, final 1280×720, 24 fps, MP4 via the built-in FFmpeg.

### 3.5 Day 0 results (21 Oct 2026, measured on the laptop)
| Check | Result |
|---|---|
| Laptop | i5-1340P, 15.7 GB RAM, Intel Iris Xe (integrated), Windows 11 |
| Blender | **4.5.14 LTS** (portable zip, sha256 verified) at `C:\Users\ysarc\tools\blender-4.5.14-windows-x64\` |
| Headless Workbench | ✅ 960×540 still 1.8 s (incl. start-up); 24-frame MP4 in 0.95 s |
| Headless EEVEE | ✅ works on the Iris Xe. Engine id in 4.5 is `BLENDER_EEVEE_NEXT`. First frame ~33 s (shader compile), then 24 frames at 1280×720, 16 samples in 23.7 s (≈1 s/frame) → a 10 s final clip ≈ 4 min |
| Ollama | ✅ v0.40.6, `qwen2.5:3b` and `qwen2.5:7b` (pulled 21 Oct) installed |
| qwen2.5:7b tool calling | ✅ 3 calls in 39 s (CPU) on the same request. Also **forgot the table**, put the figure at (1, 2, 3) (floating), and put `colour` inside `location` (wrong argument place; validation must reject it with a clear message) |
| qwen2.5:3b tool calling | ✅ 3 schema-valid calls in 23 s (CPU) for "red ball on the table, stick man walks to the table". It used the `on_top_of` helper correctly but **forgot to add the table** and **put the figure 1.5 m in the air**: exactly the failures the checks + fix loop target |
| Python / FFmpeg | 3.11.9 / FFmpeg 8.0 (Blender has its own FFmpeg too) |

### 3.4 Limits to know
- `bpy.ops` often needs a UI context; in background mode use `bpy.data`.
- The API changes between versions (e.g. the EEVEE engine id differs across 4.x and 5.x). Pin one version.
- Blender has no "understanding": it happily renders an empty frame. That's why the agent needs checks.

---

## 4. What we will build

### 4.1 Architecture
```
request ──► Agent (LLM, tool-calling loop)
              │ tool calls (JSON)            ▲ results + scene state (JSON) + check reports
              ▼                              │
         Tool layer (validated, 16 tools)    │
              │                              │
         Blender worker (headless, bpy) ─────┘ ──► .blend + check renders + final MP4
              │
         Checker: geometric + motion checks from the scene data (+ optional VLM yes/no on renders)
```
- The agent **never runs free-form Python**: only the listed tools, with validated arguments.
- After each step the tool layer returns a compact **scene state** (objects, bounds, figures and their
  actions, keyframe ranges, camera), so the LLM "sees" the scene as data.
- Errors (bad name, out-of-range value) come back as short messages the model can act on.

### 4.2 Tools (v2)
| Tool | Arguments (validated) |
|---|---|
| `scene_reset` | — |
| `scene_state` | — → objects, bounds, materials, figures, keyframe ranges, camera, frame range |
| `add_primitive` | type ∈ {cube, sphere, cylinder, plane, cone, torus}, name, location, size |
| `add_asset` | asset ∈ local library (6–8 CC0 props), name, location, scale |
| `set_transform` | name, location / rotation / scale |
| `set_material` | name, colour, preset ∈ {matte, plastic, metal, glass, glow, wood} |
| `add_light` | preset ∈ {day, studio, sunset, night} |
| `set_camera` | location, look_at (object or point), focal length |
| `camera_move` | kind ∈ {orbit, dolly_in, dolly_out, follow, pan}, target, start/end frame |
| `keyframe` | name, property ∈ {location, rotation, scale, colour}, frame, value |
| `set_easing` | name, property, interpolation ∈ {linear, ease_in_out, bounce, constant} |
| `set_frames` | start, end, fps |
| **`add_stick_figure`** | name, location, facing (degrees or toward an object), height (m), colour |
| **`play_action`** | name, action ∈ library, start frame, then one of: `cycles`, `to` (object/point), `duration`; speed; blend frames (default 6) |
| `render_check` | frames (list) → Workbench PNGs + check report |
| `render_final` | → MP4 (EEVEE, else Workbench) |

**Placement helper:** every `location` argument also accepts `{"on_top_of": obj}`, `{"next_to": obj, "side": …}`,
`{"in_front_of": obj, "distance": m}`, so the model needn't do coordinate maths.

**Camera rule:** `set_camera(look_at)` adds a Track-To constraint; `camera_move` keys the camera's position
and keeps the constraint. One mechanism, no conflict. A new fixed `set_camera(location)` clears earlier moves.

**As built (Day 1, 22 Oct):**
- `location` z is the height of the object's **bottom** (z = 0 = standing on the ground); x, y its centre.
  This removes a whole class of floating/sunk mistakes.
- `add_primitive` also takes `colour` / `preset` (both models put the colour there on Day 0).
- `set_easing` has a **`gravity`** mode: falling segments speed up, rising ones slow down, sideways travel
  stays linear. One call gives a believable bounce or jump.
- Extra internal tools (not offered to the agent): `sample_scene` (per-frame data for the checker),
  `set_output`, `save_blend`.
- Validation runs outside Blender (`blender_worker/schema.py`) and names the wrong field, e.g.
  *"unknown field 'colour'. Hint: 'colour' is a separate argument of this tool"*.

Stretch tools: `pose` (name, joint, angle, frame: custom gestures), new actions (`jump`, `sit`, `run`),
3D armature version of the stick figure, `image_plane` (P3 character parts as a 2.5D cut-out).

### 4.3 The stick figure (core)
- **Skeleton = the Project 3 motion skeleton**: 18 joints (pelvis, chest, neck, head_top, hips, knees, ankles,
  toes, shoulders, elbows, wrists) and 13 bones, plus connector bars (chest→shoulders, pelvis→hips).
- **In Blender:** each joint is an empty, keyframed per frame. Each bone is a thin cylinder that follows two
  joints (Copy Location + Stretch To constraints); the head is a sphere. Everything is parented to a **root**
  empty that carries world position and facing. The checker reads the joint empties directly.
- **Motion library = P3 `actions/*/motion.json`** (2D joint positions per frame, in leg lengths, with `meta.json`:
  view, fps, loop, stride, contact frames). Units are scaled by the figure's leg length. Side-view actions play
  in the figure's forward–up plane, front-view actions in its side–up plane. Left limbs sit slightly behind,
  right limbs slightly in front, so the figure reads in 3D.
- **Available from P3:** `idle`, `walk`, `walk_happy`, `walk_sad`, `walk_worried`, `wave`, `react`, `look_down`.
  New if time: `jump`, `sit`, `run` (P3 had a run that was later removed).
- **`play_action` details:**
  - walks loop by cycle, adding `stride_per_cycle` each cycle. `to` = walk until within reach of the target
    (number of cycles from the distance, last cycle shortened), turning the root toward it first (over ~8 frames)
  - **blending:** joint positions crossfade from the previous action over `blend` frames (ease in/out), so
    walk → stop → wave has no pops
  - **foot lock** on contact frames (as in P3) after blending, so blends don't make feet slide
  - frame rates are resampled to the scene fps (e.g. `wave` was recorded at ~29.8 fps)
- **Known limit:** the motions are 2D, so a figure looks flat when seen along its motion plane. Handled by the
  staging check (§4.4) and sensible camera defaults; a true 3D armature is a stretch goal.

### 4.4 Self-check (the agent's critic)
**Scene checks** (exact, from scene data):
- every requested object / figure exists and is **inside the camera view** (projected bounds)
- not hidden: ray casts from the camera to a few points on the object (`scene.ray_cast`)
- objects rest **on** a surface (±1 cm; props carry a support-surface height in their asset metadata), no intersections
- the camera isn't inside an object; light isn't zero

**Motion checks** (sampled on every frame with `frame_set`, so easing is included):
- object motion: bounce count (local minima touching the surface), spins, start/end positions, duration
- **figure grounded:** lowest toe/ankle within ±1 cm of the floor on contact frames, never below it
- **no foot slide:** planted foot moves ≤ 0.5 cm per frame
- **no pops:** no joint speed above 3× that action's median speed at action boundaries
- **reaches the target:** ends within 0.3 m of `to`, facing it
- **actions in order:** the requested story beats appear in the figure's timeline in the right order
- **staging:** angle between the camera's view and the action's motion plane is ≤ 45° (side actions seen from
  the side, front actions from the front)
- two figures don't walk through each other or through props

**As built (Day 1):** the worker's `sample_scene` records every frame (exact vertex bounds, screen box,
camera vectors; visibility and collisions every 6th frame) and `checks/checker.py` evaluates it in plain
Python. Visibility = share of camera-facing face points the camera reaches (a table is sampled on its legs
and top, not through the gap between them). Collisions = BVH overlap with each mesh shrunk 1 cm, so resting
contact doesn't count. Roles are bound to objects by kind + colour, trying every assignment and keeping the best.
`tests/test_checker.py` builds 9 deliberately broken scenes; each fails exactly the expected check.
Known gap: an object moving sideways in mid-air ("hovering") isn't caught yet.

**Visual check (optional):** a small local VLM via Ollama (e.g. `qwen2.5vl:3b`) answers 3–5 yes/no questions
on the check renders. One vote, never the only check (as in Project 3).

Failure → the report goes back to the agent → it fixes with tools (max 3 rounds). Every decision is logged.

### 4.5 Agents compared
| ID | Brain | Cost |
|---|---|---|
| A0 | template baseline: rules → fixed tool sequence | free |
| A1 | `qwen2.5:3b` via Ollama (tool calling) | free, laptop |
| A2 | `qwen2.5:7b` via Ollama | free, laptop (slower) |
| A3 | Claude via an MCP server with the same tools, scripted with `claude -p` | subscription, no API spend |

Same tools and checks for all. A3's time per task isn't comparable (remote model, rate limits), so its timing is reported as indicative only.

---

## 5. Evaluation
**Task set: 30 requests, written before building, each with a machine-checkable spec (`tasks.json`).**
It follows the animation-training ladder:

| Category | # | Examples |
|---|---|---|
| Warm-up: static layout | 3 | "three cubes in a row, the middle one blue" |
| Warm-up: object motion | 5 | "the ball bounces 3 times", "the cube spins once in 2 s" |
| Stick figure: single action | 6 | "a stick man walks to the right for 4 s", "she waves at the camera" |
| Stick figure: sequence | 6 | "he walks in, stops, looks down, then walks away sadly" |
| Stick figure + props | 6 | "he walks to the table and waves", "she walks around the box" |
| Two figures + camera | 4 | "two stick figures walk toward each other and stop face to face; the camera slowly dollies in" |

Example `tasks.json` entry:
```json
{
  "id": "fig_props_01",
  "request": "a stick man walks to the table and waves",
  "checks": [
    {"exists": "table"}, {"figure_count": 1},
    {"actions_in_order": ["walk", "wave"]},
    {"reaches": {"figure": "*", "target": "table", "within_m": 0.3}},
    {"grounded": "*"}, {"no_foot_slide": "*"}, {"no_pops": "*"},
    {"in_view": ["table", "*"]}, {"staging": "*"}
  ]
}
```
(`"*"` = any figure; names chosen by the agent are matched by kind.)

**Metrics:** task success (all checks pass); per-check pass rate; valid tool-call rate (schema-valid, correct
names); steps and fix rounds; time per task; VLM agreement with the geometric checks.

**Studies:**
1. Model: A0 vs A1 vs A2 vs A3
2. Scene-state feedback on/off. "Off" also removes the `scene_state` tool, so a model can't fetch it anyway.
3. Self-check loop on/off (success before vs after fixes)
4. Failure analysis: wrong coordinates, forgotten objects or beats, wrong order, bad staging, camera misses

**Human check:** rate 10 final clips 1–5 ("does it match the request?" and "does the motion look good?") against the automatic score.

---

## 6. Deliverables
- `blender_worker/` (headless worker + tools + stick figure), `agent/` (loop, prompts, backends), `checks/`,
  `tasks.json`, `eval.py`; motion library copied from P3 `actions/` with its `sources.md`
- MCP server exposing the tools (used by A3; also lets anyone drive Blender from Claude)
- Results tables + clips; report (with the §0 story)
- **Deployment:** static showcase page (requests → clips, results, failure gallery) on a free Hugging Face Space;
  live demo from the laptop via a Gradio share link, as in Project 3
- Transcript of the Claude Code session → HTML (turns collapsed)

## 7. Timeline
| Day | Work |
|---|---|
| Tue 21 Oct | Spec v2. **Day 0 checks:** Blender installed (record version), headless render, EEVEE or Workbench fallback, Ollama tool calling with qwen2.5. Write `tasks.json` (30 tasks + checks). |
| Wed 22 Oct | Worker + object tools + scene state + placement helpers + scene/object-motion checks; template baseline A0 |
| Thu 23 Oct | Stick figure + `play_action` (cycles, `to`, blending, foot lock) + figure motion checks |
| Fri 24 Oct | Agent loop (A1/A2), fix loop, MCP server + A3; first full eval run |
| Sat 25 Oct | Studies 2–4, tables, showcase clips, failure gallery, human ratings |
| Sun 26 Oct | Report, deploy, transcript; buffer. Optional if ahead: P3 layered-art upgrade (separate) |
| Mon 27 Oct | Final checks, submit by 2 pm |

## 8. Risks
| Risk | Mitigation |
|---|---|
| EEVEE fails headless | Workbench for everything (clean flat look suits stick figures) |
| Small LLMs give bad tool calls / coordinates | validated schemas, error messages returned, scene state, placement helpers, `play_action(to=…)` so the model never computes walk distances |
| Pops / foot slide at action transitions | crossfade + foot lock after blending; `no_pops` / `no_foot_slide` checks catch the rest |
| 2D motions look flat from some angles | staging check + side/front camera defaults; 3D armature only as stretch |
| P3 motion files need adapting (units, fps, views) | read `meta.json`; resample fps; scale by leg length; test each action on Day 2 |
| Blender API differences | pin one version, use `bpy.data` |
| Eval runtime on a laptop (30 tasks × 4 agents + ablations, up to 3 fix rounds) | Workbench check renders, cache LLM calls, run overnight 24→25 Oct |
| Scope creep | v2 core = objects + stick figures + camera; jump/sit/run, pose, 3D rig are stretch |

## 9. Out of scope
Drawn/textured characters (that was Project 3), modelling from scratch, real 3D character rigging, physics,
photoreal Cycles renders, free-form code execution, Geometry Nodes, Grease Pencil, long films.

## 10. Acceptance criteria
- With at least one **LLM** backend (A1–A3, not the template A0), the agent completes ≥ 60% of the 30 tasks end to end, with results reported for all backends
- ≥ 5 stick-figure clips pass all checks and get a human rating of ≥ 4/5 for "motion looks good"
- Self-check loop measured (success before vs after fixes)
- Deployed showcase URL; report + transcript submitted before 27 Oct 2026, 2 pm

## 11. Future work: from stick figures to proper 2D characters
The stick figure is the **motion layer**. A drawn 2D character is an **appearance layer on the same skeleton**,
so the agent, tools, motion library, blending, foot lock, checks and Blender pipeline all carry over unchanged.

| Step | What | Why |
|---|---|---|
| 1. Layered character art | each part drawn whole on its own layer (head, torso, upper/lower arms, hands, legs, shoes), as PSD or PNGs | removes Project 3's bottleneck: no cutting of flat art, no guessed hidden areas (how professional cut-out rigs are made) |
| 2. Parts on the skeleton | each part as an image plane attached to a stick-figure bone (`image_plane` tool), pivots at the joints | the character performs every existing action with no new animation work |
| 3. Views | separate side / front / ¾ drawings, swapped when the figure turns | 2D characters can't rotate; animators swap drawings |
| 4. Faces | Project 3's face layers + expression recipes (smile, sad, shocked, blinks) | already built in Project 3 |
| 5. Style | Blender line art, flat shading, painted backgrounds | reads as 2D animation, not 3D |
| 6. (Alternative) Grease Pencil | character drawn with strokes in Blender, rigged to the same skeleton | more hand-drawn look, more manual work |

**Realistic expectation:** for characters drawn in layers, this gives good-looking, agent-directed 2D cut-out
animation (the same method as many TV and YouTube series, and tools like Moho or Spine). Fully automatic
animation from *any* flat character sheet stays a research problem (Project 3's finding), and AI redraw
passes on top bring drift back.

## 12. Related work (check exact details before citing)
- **BlenderMCP** (open source, 2025): Claude ↔ Blender via MCP with an add-on socket server
- **3D-GPT** (2023): LLM agents generating 3D scenes through procedural Blender code
- **SceneCraft** (2024): LLM agent writing Blender scripts, refined with a vision-model critic
- **BlenderAlchemy** (2024): VLM edits Blender materials/scenes iteratively
- **Toolformer** (2023), **ReAct** (2022): tool use / reason-act loops
- **Model Context Protocol** (Anthropic, 2024): the standard for exposing tools to LLMs
- R. Williams, *The Animator's Survival Kit* (2001): ball → figure → walk training ladder; pose-to-pose blocking
- Project 3 (own work): motion library, foot lock, critic + fix loop
