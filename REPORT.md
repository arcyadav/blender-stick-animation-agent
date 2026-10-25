# An Agent That Directs Stick-Figure Animation in Blender

**UMC301 Project 5 · Archana Yadav · October 2026**

- Deployed page: https://arcyadav-stick-animation-agent.static.hf.space
- Code: https://github.com/arcyadav/blender-stick-animation-agent
- Local live demo: `python demo_app.py`

---

## Abstract

Generative video gives no control over the result and no editable file, and characters drift between
frames. Professional animation software gives full control but needs a skilled operator. This project sits
between the two. An AI agent operates real software (Blender) through a small set of validated tools, so the
result is an editable scene that can be checked exactly. The agent turns a plain-language request ("a stick
man walks to the table and waves") into a short 2D stick-figure animation. It then checks the scene from
Blender's own data (feet on the ground, no foot slide, actions in order, everything in view) and fixes what
fails, up to three rounds. Four directors use the same 16 tools on the same 30 tasks: template rules (A0),
qwen2.5 3b (A1), qwen2.5 7b (A2) and Claude through an MCP server (A3). Claude passes all 30 tasks (27 on the
first try, 3 fixed from the checker's report) with no invalid calls. qwen2.5 7b passes 8 and qwen2.5 3b
passes 3; one in five of their calls is invalid, and they rarely turn a failing report into a pass. The
template rules also pass 30/30, but they were written while looking at these requests. With the same tools,
Claude also directs multi-shot stories, such as a 54-second, seven-shot story in 44 tool calls with no
errors. The motion library comes from Project 3, which shows the design choice behind this project:
motion and appearance are separate problems.

---

## 1. Introduction

**Why this project.** Project 3 aimed straight for the hard version: a drawn character from a character
sheet, cut into parts and driven by a motion library. The motion transferred to a second character with no new
animation work, but the *appearance* broke. Cutting flat drawings into parts meant guessing the areas
hidden behind other parts, and those guesses showed up as seams (Project 3, `docs/reuse_test.md`). The lesson
was that motion and appearance are separate problems, and appearance is the harder one.

Project 5 separates them. Rendering is done by professional software (Blender). The characters are stick figures,
so only the motion matters. An AI agent directs the scene through tools. This is also how animators are
trained: *The Animator's Survival Kit* starts with the bouncing ball, then a simple figure, then the walk
[1], and animators block shots with simple rigs before the final art. The task set follows the same ladder.

**Research question.** *How reliably can language models of different sizes direct animation in professional
software through tools, and how much does a self-check loop help?*

**What "good" means here:** grounded (no foot slide or floating), smooth (no pops between actions), timed
(eased, with holds), readable (the camera shows the action), and the requested story beats in order. The
target is clean animation blocking, not finished film.

**Contributions.**
1. A headless Blender worker with 16 validated tools for a 2D world, including stick figures that play
   17 actions with blending, foot locking, facing rules, sitting and carrying.
2. A checker that verifies each result from scene data, frame by frame, and writes its report for the agent.
3. A comparison of four directors on 30 tasks under identical tools and checks, with a self-check loop.
4. Story mode, which directs long animations shot by shot, and a deployed page with every final run.

## 2. Background

**Blender from code.** Blender is free and open source, and everything in it is scriptable in Python
(`bpy`). It runs without a window (`blender -b`), so a long-running worker process can receive commands
and edit one scene. Blender has no understanding of the scene: it will happily render an empty frame. An
agent therefore needs checks that read the scene, not just a renderer.

**Language models with tools.** A model that calls tools and reads their results can act in an environment
step by step (ReAct [2]). Feeding a failure back to the model so it can correct itself is a known way to
improve results (Reflexion [3]). The Model Context Protocol (MCP) [4] is an open protocol for offering tools
to a model; BlenderMCP [5] connects Claude to a running Blender through it. This project differs in three
ways: the tool set is small and validated rather than "run any Python"; the world is 2D, so every result
can be checked; and the result is scored by a checker rather than by eye.

**Models.** qwen2.5 3b and 7b [6] are open models with tool calling, run locally through Ollama [7]. Claude
runs through Claude Code (`claude -p`) on a subscription, with only this project's MCP server as its tools.

## 3. System

### 3.1 Architecture

```
request ──► agent (A0 rules | A1/A2 qwen via Ollama | A3 Claude via MCP)
               │ tool calls (JSON)                 ▲ results, scene state, check report
               ▼                                   │
        validation (schema) ──► Blender worker (headless, one scene) ──► checker (scene samples)
                                         │
                                         ▼
                                 MP4 + editable .blend
```

The Blender worker is one long-running process that receives JSON tool calls over a local socket. Every
call is validated before Blender sees it; an invalid call comes back as an error message that names the
problem ("play_action: missing required argument 'action'") and changes nothing. The checker asks the
worker for a sample of the scene (positions, joint tracks, action timeline and camera every frame;
visibility and collisions every sixth frame) and evaluates it in plain Python.

### 3.2 A 2D world

After the first renders (22 Oct) the look changed from "3D toy" to a flat 2D world: flat colours, a white
background, a ground line, seen from the side through an orthographic camera. Stick figures are a 2D art
form, and the Project 3 motions are 2D anyway. Positions are `[x, z]` (left/right, height). Depth is only a
layer (back, middle, front) that decides what is drawn over what; things in different layers never collide,
so props a figure walks past go in the back layer. The camera pans, zooms and follows. Rendering uses
Blender's Workbench engine and takes about a second of rendering per second of video on the laptop.

### 3.3 Tools

Sixteen tools: `scene_reset`, `scene_state`, `add_primitive` (sphere, cube, cylinder, cone, torus),
`add_asset` (table, chair, bench, box, lamp, tree, built from primitives with a known top height),
`set_transform`, `set_material`, `add_light` (presets), `set_camera`, `camera_move` (pan, zoom, follow),
`keyframe`, `set_easing` (including a gravity curve for bounces), `set_frames`, `add_stick_figure`,
`play_action`, `render_check` and `render_final`.

Two design choices keep small models away from arithmetic they get wrong:
- **Placement helpers:** `{"on_top_of": "table"}` and `{"next_to": "box", "side": "left"}` instead of coordinates.
- **Targets instead of distances:** `play_action(action="walk", to="table")` computes the walk itself, and an
  action with `to` (look, wave, react, pick_up, sit) faces and aims at that object.

Errors are written for the model to act on: a failing "nothing matches 'table'" says how to make one
(`add_asset(asset='table')`), and a third identical successful call is answered with "already done, do the
next step" (the repeat guard; qwen 3b once made 36 identical `set_camera` calls).

### 3.4 Stick figures and the motion library

A stick figure is a single curve object whose joints are keyframed every frame from a pure-Python
motion module (`blender_worker/motion.py`), which can therefore be tested without Blender.
- **Captured motion:** the walk and its three moods (happy, sad, worried) are Project 3's 2D joint tracks;
  the front wave was recorded from my own video and exaggerated for a stick figure.
- **Keyed and computed actions:** idle (breathing), look, look down, react (a fright), sigh, run, handshake,
  pick up / put down, sit / stand up and turn. These are keyed poses, or computed from the scene: the
  arm reaches the actual ball, the knees bend to the actual seat height, and two figures shuffle to a
  comfortable handshake distance.
- **Joining actions:** adaptive blends with quintic easing; the turn happens before the next action; walks
  speed up over the first step and end with a settle step; runs brake first; the planted foot is locked to
  the ground so it never slides.
- **Rules learned from looking at clips:** a figure keeps its last side-on facing instead of turning to the
  camera between actions; a short walk backwards is played as back-steps; a seated figure never swivels;
  a carried object's own earlier keyframes (a ball that bounced in) are kept.

### 3.5 The checker

Each task lists its own checks, and nine default checks apply to every task:

| Default check | Passes when |
|---|---|
| `in_view`, `not_hidden` | every object is inside the frame and not covered, most of the time |
| `on_surface`, `no_hover`, `no_collision` | things rest on something, nothing hangs in the air, nothing passes through anything |
| `grounded` | every figure's lowest foot is within 1.5 cm of the ground every frame |
| `no_foot_slide` | a planted toe moves at most 0.5 cm per frame |
| `no_pops` | no joint jumps or spikes between frames (acceleration test against the neighbouring frames) |
| `clip_length_s` | the clip is 2–20 s long |

Task checks include `count`, `row`, `relation`, `bounces`, `spins`, `moves`, `colour_change`,
`camera_move`, `actions_in_order`, `action_duration`, `reaches` (and faces), `returns`, `same_time` and
`passes`. Roles in a task ("the table", "the walker") are bound to scene objects by kind and colour, trying
every assignment and keeping the best, so the agent's own names don't matter. Two test suites build
deliberately broken scenes (a moonwalk, a teleporting arm, a floating figure, a ball through a table) and
confirm that each fails exactly the expected check.

### 3.6 The four directors

| ID | Director | Runs on |
|---|---|---|
| A0 | template rules: keyword patterns turn the request into a fixed sequence of tool calls | laptop |
| A1 | qwen2.5 3b, tool calling through Ollama | Kaggle T4 GPU |
| A2 | qwen2.5 7b, the same | Kaggle T4 GPU |
| A3 | Claude via `claude -p` with this project's MCP server as its only tools | Claude subscription |

A1–A3 get the same system prompt (the tools, the 2D world, the action list, and short rules such as "make
only what is asked"). **Self-check loop:** when the agent says it is done, the checker runs; a failing
report goes back to the agent, which fixes the scene with the same tools, at most three times. A1/A2 get the
report as a message; A3 calls a `check_scene` tool. The MCP server for A3 is hand-written (JSON-RPC over
stdio) and attaches to the evaluation's own Blender worker, so the checker sees exactly Claude's scene.
qwen runs on a Kaggle T4 GPU behind a Cloudflare tunnel (laptop CPU took 3.5–9.5 minutes per task); Blender
and the checker stay on the laptop.

### 3.7 Story mode

A long story asked in one go makes the agent plan every beat at once, and an early mistake breaks a later
beat. Story mode (`story.py`) splits a story into shots, like an animator's storyboard. Each shot is a short
request that continues the same scene; the agent is told what already exists and where the timeline ends.
Characters new in a shot appear when the shot starts, and the camera is directed once at the end, over the
whole timeline.

## 4. Experimental setup

**Tasks.** Thirty requests were written before the system was built, each with a machine-checkable spec in
`tasks.json`, following the animation ladder:

| Category | Tasks | Example |
|---|---|---|
| Static layout | 3 | "three cubes in a row, the middle one blue" |
| Object motion | 5 | "a red ball bounces three times on the floor" |
| Figure, single action | 6 | "a stick figure waves at the camera" |
| Figure, sequence | 6 | "she walks in, stops, looks down, then walks away sadly" |
| Figure with props | 6 | "a stick man walks to the table and waves" |
| Two figures and camera | 4 | "two stick figures walk toward each other, stop face to face and shake hands; the camera slowly zooms in" |

**Settings.** qwen runs at temperature 0 with seed 0 and an 8k context. Because of that, the first round of
each run is exactly what the agent would do without the fix loop, so success before and after fixing comes
from one run. Up to 3 fix rounds. One run per agent per task. The final runs were made on 25 Oct 2026 on the
frozen version of the system (results in `results/final_2026-10-25`). Timings for A1/A2 are on the Kaggle
GPU and for A3 on Anthropic's servers, so they are indicative, not comparable.

**Metrics.** Task success (all checks pass); success on the first try; tool calls per task; invalid calls
(rejected by validation); tool errors (valid calls that failed, e.g. a walk to a missing object); time.

**Replays.** The evaluation doesn't render, so each run's clip was rebuilt afterwards by replaying the
agent's own successful tool calls in order (`scripts/replay_results.py`). The checker runs again on the
replayed scene. **All 120 replays give the same pass or fail as the recorded run**, which also confirms
that the results don't depend on anything outside the logged calls.

## 5. Results

### 5.1 Study 1: which director?

| Agent | Passed | First try | Calls / task | Invalid calls | Tool errors | Time / task |
|---|---|---|---|---|---|---|
| A0 template rules | **30 / 30** | 30 | 7.1 | 0% | 0% | 0.3 s |
| A1 qwen2.5 3b | **3 / 30** | 2 | 57.6 | 21% | 23% | 58 s |
| A2 qwen2.5 7b | **8 / 30** | 8 | 18.3 | 21% | 26% | 56 s |
| A3 Claude (MCP) | **30 / 30** | 27 | 6.2 | 0% | 1% | 18 s |

By category:

| Category | A0 | A1 | A2 | A3 |
|---|---|---|---|---|
| Static layout | 3/3 | 0/3 | 1/3 | 3/3 |
| Object motion | 5/5 | 0/5 | 0/5 | 5/5 |
| Figure, single action | 6/6 | 2/6 | 5/6 | 6/6 |
| Figure, sequence | 6/6 | 1/6 | 1/6 | 6/6 |
| Figure with props | 6/6 | 0/6 | 0/6 | 6/6 |
| Two figures and camera | 4/4 | 0/4 | 1/4 | 4/4 |

Claude directs every task with about six calls and no invalid ones, close to the hand-written rules' seven.
The qwen models do best on single figure actions (A2: 5 of 6), where one or two calls are enough, and fail
almost everything that needs several objects placed in relation to each other or several beats in order.
Going from 3b to 7b cuts the calls per task by two thirds (57.6 → 18.3) and nearly triples the passes,
but the invalid-call rate stays at one in five. A first full run two days earlier gave the same picture
(A1 2/30, A2 8/30, A3 30/30 with 27 on the first try).

**The template rules' 30/30 is a ceiling, not a fair comparison.** The rules were written while looking at
these 30 requests. In the live demo they silently dropped every action they had no keyword for ("sits
down", "looks up at a tree") until rules for the newer actions were added; the rule set then still passed
30/30, with only one task's calls changing. Rules work exactly as far as someone has written them.

### 5.2 Study 3: does the self-check loop help?

| Agent | Failed first try | Fixed from the report | Passed in the end |
|---|---|---|---|
| A3 Claude | 3 | **3** | 30 |
| A1 qwen 3b | 28 | 1 | 3 |
| A2 qwen 7b | 22 | 0 | 8 |

For Claude, the loop turned every first-try failure into a pass, each in one round, and each from a
one-line report:
- "ball bounces 2 time(s), expected 3" → added a third bounce (m01)
- "tree not fully in view on 56 frames" → widened the following camera (p06)
- "gap between red and blue is 0.68 m (max 0.5)" → moved the figures closer (t02)

The qwen models read the same kind of report but almost never turned it into a working fix. qwen 3b's one
fix (q05) is partly luck: its final scene has the required beats in order but also extra ones (a sit and a
look down) that the task's check doesn't forbid. So the self-check loop only helps when the model can map
a failure onto the right tool call, and that ability is what separates the model sizes here.

### 5.3 Study 4: why do the small models fail?

Failing checks, counted once per failed run:

| Failure type | A1 (27 failed) | A2 (22 failed) |
|---|---|---|
| Missing or wrong beat, or wrong order (`actions_in_order`, `reaches` …) | 15 | 8 |
| Placement: floating, sunk or overlapping (`on_surface`, `no_hover`, `no_collision`) | 9 | 9 |
| Camera and framing (`in_view`, `not_hidden`) | 7 | 11 |
| Object motion wrong (`bounces`, `spins`, `moves` …) | 9 | 5 |
| Clip too long or short | 5 | 6 |
| Forgot an object or figure | 4 | 5 |

Errors in their tool calls, over all 30 tasks:

| Call error | A1 | A2 | A3 |
|---|---|---|---|
| Repeat guard ("already done, do the next step") | 347 | 114 | 0 |
| Missing a required argument | 306 | 106 | 0 |
| Refers to an object that doesn't exist | 126 | 32 | 2 |
| Tries to keyframe or ease a stick figure directly | 97 | 77 | 0 |

The pattern behind these numbers:
- **Order of work.** qwen often refers to things before making them: it places a figure "next to the
  bench" before adding the bench.
- **Loops.** It repeats a call that already worked: the repeat guard fired 347 times for qwen 3b.
- **Raw coordinates.** It uses coordinates where a helper exists, which leaves props floating at the
  height it guessed.
- **Its own timing.** It adds `start_frame`s that make actions overlap. In the live demo, qwen 7b put a
  "look" at frame 15 and a "sigh" at frame 20 while the sit (with its walk to the bench) only started at
  frame 89, so the figure never sat.
- **Wiping its work.** It calls `scene_reset` in the middle of a task, erasing the scene it built (A2, q05).

Claude's two tool errors were both lookups of a name that didn't exist yet, corrected on the next call.

### 5.4 Stories

Using story mode, Claude directed two stories with the same tools:

| Story | Shots | Tool calls | Errors | Length |
|---|---|---|---|---|
| *The Lost Ball*: a ball bounces in; Red finds it, looks around, sees sad Blue on a bench, gives him the ball; they wave | 7 | 44 | 0 | 54 s |
| *The Ball That Goes Away*: a ball rolls off a bench; a man chases it, gives up, sits on another bench; it rolls back, then away again | 6 | 64 | 0 | 34 s |

These go well beyond the 30 tasks: a figure holding a ball while turning to look around, a front-facing sit
on a bench, putting a ball down beside a seated figure, a chase with the camera following. Writing them
also exposed real bugs that the 30 tasks never triggered, all fixed:
- the camera's `follow` kept a gap measured at the wrong frame, so the camera trailed 14 m behind the man
- a figure looked at where a ball was at frame 1, not where it was when he looked
- a picked-up ball lost its earlier bounce keyframes

Two video edits were made outside the tools: the second story starts 2.5 s in, so it opens with the man
already seated, and ends with 1.5 s of black, because there is no "fade to black" tool.

### 5.5 Human rating

The spec planned a scored rating (1–5) of 10 clips. Instead, I reviewed the final clips (Claude's runs of
the figure tasks, and both stories) informally against the standard of stick-figure cartoon animation, which
is not meant to look realistic. My judgement: the actions read clearly and look good enough for this style;
each request's beats are recognisable, and the motion has no visible sliding, popping or floating, which
agrees with the automatic checks. Problems I did see during development were reported and fixed as bugs
(§5.4) rather than scored. No per-clip numbers were recorded, so this is a qualitative check by one viewer,
the author.

## 6. Discussion

**Tools make the difference small models can't.** Every helper that removes arithmetic (placement by
relation, walking to a target, aiming at an object) moved work from the model into tested code, and the
best agent's calls are short and declarative. The 3b model's failures are mostly not animation mistakes but
bookkeeping: calling things that don't exist, leaving out arguments, repeating itself.

**The checker is what makes the comparison honest.** Without it, a qwen scene with a floating table and a
figure that never sits would still render a plausible video. Because every result is read from scene data,
"30/30" means every request's beats happened, in order, with feet on the ground, in view.

**Feedback helps only a model that can use it.** The self-check loop fixed all of Claude's three failures
and almost none of qwen's. A smaller model would need more structure to use it, such as a report
that names the exact tool call to change, or a planner that writes the list of beats before any tool call.

**Stories need shots, as animators use them.** Asking for a story shot by shot kept each request small, and
the camera directed at the end could see the whole timeline. Looking at the stories also found bugs the
tasks never reached, which suggests the task set is a floor for testing, not a ceiling.

## 7. Limitations

- **A0's rules were tuned on the test requests,** so its score is an upper bound for templates. Reworded,
  held-out requests would measure how brittle it is; they were not run.
- **Study 2** (removing the `scene_state` tool to measure the value of scene feedback) was planned but not
  run.
- **No scored human rating.** The motion quality was judged informally by the author (§5.5), not scored
  by independent viewers.
- **The checks are a partial spec.** They confirm what was asked but don't forbid extras; qwen 3b's fix on
  q05 passes while also sitting down, which nobody asked for.
- **One run per agent and task.** qwen runs at temperature 0 and is repeatable; Claude is not, and a second
  run could differ on a task or two (Claude's first full run, two days earlier, gave the same 30/30 with 27
  on the first try).
- **Two changes after the feature freeze,** both checked against the eval: A0 learned the newer actions
  (still 30/30; one task's calls changed), and the follow camera's bug fix (all 120 replays on the fixed tools
  give the recorded pass/fail).
- **2D only, side and front views.** No 3D staging, no physics, no lip sync. Stick figures can't show faces,
  so expression comes only from posture.
- **Deployment is static.** Hugging Face now charges for Spaces that run code, so the deployed page shows
  the final runs and clips, and live directing runs on the laptop. A Docker setup for a live server was
  built and tested on Linux (`space/Dockerfile`) but not deployed.

## 8. Deployment and reproducibility

- **Page:** https://arcyadav-stick-animation-agent.static.hf.space: the two stories, the action library,
  the results, and a browser for all 120 final runs (each agent's tool calls, its checks and the replayed
  clip; e.g. `#A1.q05`). Built by `space/build_static.py`.
- **Live demo:** `python demo_app.py` (Gradio). Type a request or run a story or a task with Claude, qwen
  (set the Ollama URL) or the template rules, and watch the tool calls and checks live.
- **Re-running:** `python eval.py --agent A3` (results in `outputs/eval/A3`), `python story.py
  stories/lost_ball.json`, `python -m scripts.results` for the tables. qwen on a GPU: start
  `kaggle/ollama_gpu_server.ipynb` and set `P5_OLLAMA_URL` to its tunnel URL.
- **Pinned:** Blender 4.5.14 LTS, Python 3.11, Ollama models `qwen2.5:3b` / `qwen2.5:7b`, Gradio 5.50.
- **Tests:** `python -m tests.test_schema`, `test_placement`, `test_checker`, `test_figure_checks`, `test_mcp`.

## 9. Future work: from stick figures to drawn characters

The stick figure is the motion layer. A drawn character is an appearance layer on the same skeleton: each
body part an image pinned to a bone, so the character plays every existing action, and the agent, tools
and checks carry over unchanged.

Project 3's character parts could be used directly, but they show the hard part. Parts cut from one
flat drawing have no art where other parts covered them (the torso under the arm, the thigh under the
shirt), so rotating parts open holes and seams. Project 3 guessed those areas automatically, and the guesses
showed. The options, from most to least reliable:
1. **Draw each part whole on its own layer,** as professional cut-out animation does (Moho, Spine, Toon Boom).
   Nothing is hidden, so nothing has to be guessed.
2. **Design joints that can't gap:** round ends at the elbows and knees, limbs slightly longer than their bones
   so neighbours overlap, and a fixed stacking order.
3. **Inpaint the hidden areas** with an image model. Better than Project 3's fill, but still a guess that
   can flicker as parts move.
4. **Costume the stick figure in Blender:** thick, coloured limbs (sleeves, trousers, shoes) and a drawn head,
   drawn whole every frame. Less painterly, but there is nothing hidden to fill.

Options 1 and 2 together are the real path, with 4 as a quick step on the way.

**What a short attempt showed** (kept on the `character-looks` branch, not part of the evaluated system):
- **Option 4,** a costumed stick figure with clothes colours and a face whose mouth follows the action, was
  easy to build and gap-free, but it looked plain.
- **Option 1, with a Gemini character.** I generated part sheets (side and front, on flat green) and rigged
  them onto the skeleton:
  - cutting the parts out and filling the hidden joint notches with discs worked;
  - the front view needed a joint chain, because the stick skeleton is far narrower than a drawn body;
  - sitting needed the legs squashed;
  - carrying an object while facing the camera did not line up.

  Getting a drawn character to look right in every action is a project of its own, so it stays future work. Other next steps: held-out requests and
Study 2; a planner step for small models (beats first, then tool calls); and more actions in the library
(jump, kick, push), each with its own check.

## 10. Conclusion

An agent can direct real animation software through a small set of validated tools, and the result can be
checked exactly. With these tools Claude passes all 30 tasks, fixes its own three failures from a one-line
report, and directs multi-shot stories without errors. qwen2.5 3b and 7b pass 3 and 8. Their gap is mostly
bookkeeping (missing arguments, references to things not yet made, repeated calls), and the self-check loop
can't close it, because they can't turn a report into the right fix. The project's design choice held up:
with appearance kept simple, motion, staging and timing could be built, checked and directed reliably. The
next step is to give the same skeleton a drawn character.

## References

1. R. Williams. *The Animator's Survival Kit.* Faber & Faber, 2001.
2. S. Yao et al. ReAct: Synergizing Reasoning and Acting in Language Models. ICLR 2023.
3. N. Shinn et al. Reflexion: Language Agents with Verbal Reinforcement Learning. NeurIPS 2023.
4. Anthropic. Model Context Protocol specification. https://modelcontextprotocol.io
5. S. Ahuja. BlenderMCP. https://github.com/ahujasid/blender-mcp
6. Qwen Team. Qwen2.5 Technical Report. arXiv:2412.15115, 2024.
7. Ollama. https://ollama.com
8. Blender Foundation. Blender 4.5 LTS Python API. https://docs.blender.org/api/4.5/
