"""Interactive demo (runs on this laptop): type a request, or pick a story or a task, choose a director,
and watch it direct the scene in Blender: tool calls stream in live, then the clip plays.

    python demo_app.py                  # opens http://127.0.0.1:7860
    python demo_app.py --share          # also a public https://….gradio.live link (runs on this laptop)
    $env:P5_PASSWORD="…"; python demo_app.py --share     # the link asks for user "viva" + this password
    $env:P5_OLLAMA_URL="https://…"; python demo_app.py      # qwen on a Kaggle GPU

Directors: A3 Claude (claude -p, MCP), A2 / A1 qwen2.5 7b / 3b (Ollama), A0 template rules.
"""
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

import gradio as gr

import config
from agent.claude_agent import ClaudeAgent
from agent.llm_agent import LLMAgent
from agent.template import Template
from blender_worker.client import BlenderWorker
from checks.checker import check_task, report_text

# P5_PUBLIC=1 (the Hugging Face Space): only the template rules direct live, since Claude runs on the
# owner's subscription and qwen on a Kaggle GPU; every agent's saved final run can still be browsed.
PUBLIC = os.environ.get("P5_PUBLIC") == "1"
DIRECTORS = {"Claude (A3)": "A3", "qwen2.5 7b (A2)": "A2", "qwen2.5 3b (A1)": "A1", "Template rules (A0)": "A0"}
if PUBLIC:
    DIRECTORS = {"Template rules (A0)": "A0"}
RESULTS = Path(os.environ.get("P5_RESULTS", config.ROOT / "results" / "final_2026-10-25"))
CLIPS = Path(os.environ.get("P5_CLIPS", config.OUTPUTS / "replays"))
AGENT_NAMES = {"A0": "Template rules", "A1": "qwen2.5 3b", "A2": "qwen2.5 7b", "A3": "Claude (MCP)"}
EXAMPLES = [
    "a stick man walks to the table and waves",
    "a red ball bounces three times on the floor",
    "two stick figures walk toward each other, stop face to face and shake hands",
    "a stick figure walks to a bench, sits down, looks up at a tree and sighs",
    "a stick man walks to a chair with a ball on it, picks up the ball and walks off happily",
    "a stick figure stands around, gets startled, then runs off to the right",
]
TASKS = json.loads((config.ROOT / "tasks.json").read_text(encoding="utf-8"))
TASK_BY_LABEL = {f"{t['id']} · {t['request']}": t for t in TASKS["tasks"]}
STORIES = sorted(p.name for p in (config.ROOT / "stories").glob("*.json"))
OUT = config.OUTPUTS / "demo_app"


def _agent(code, fix_rounds=0):
    if code == "A0":
        return Template()
    if code == "A3":
        return ClaudeAgent("A3", fix_rounds=fix_rounds)
    return LLMAgent("qwen2.5:7b" if code == "A2" else "qwen2.5:3b", code, fix_rounds=fix_rounds)


def _line(c):
    args = json.dumps(c["args"], ensure_ascii=False)
    if len(args) > 150:
        args = args[:150] + "…"
    err = f"\n    ✗ {c['error'][:220]}" if c.get("error") else ""
    return f"{c['tool']} {args}{err}"


def _run(job, out_dir):
    """Run job(w, log) in a thread; yield (log text, done, result) while it runs. Claude logs to a file
    (its MCP server), so that file is tailed too."""
    log, q = [], queue.Queue()
    holder = {}

    def target():
        try:
            with BlenderWorker(out_dir) as w:
                w.call("set_output", subdir="")
                holder["result"] = job(w, lambda tool, args, err: log.append(
                    {"tool": tool, "args": args, **({"error": err} if err else {})}))
        except Exception as e:                       # shown to the user, not a crash of the app
            holder["error"] = f"{type(e).__name__}: {e}"
        q.put(True)

    threading.Thread(target=target, daemon=True).start()
    t0 = time.time()
    while q.empty():
        time.sleep(0.7)
        yield _render_log(log, out_dir, t0), False, None
    yield _render_log(log, out_dir, t0), True, holder


def _render_log(log, out_dir, t0):
    lines = [c["args"][""] if c["tool"] == "──" else _line(c) for c in log]
    runs = sorted(Path(out_dir).glob("claude_runs/*/mcp_calls.jsonl"), key=lambda f: f.parent.stat().st_ctime)
    for f in runs:                    # Claude's calls arrive through its MCP server's log, live
        if len(runs) > 1:
            lines.append(f"── {f.parent.name}")
        for row in f.read_text(encoding="utf-8").splitlines():
            e = json.loads(row)
            if "check" in e:
                lines.append(f"── check_scene: {'PASS' if e['passed'] else 'FAIL'}")
            else:
                lines.append(_line({"tool": e["tool"], "args": e["args"],
                                    **({"error": e.get("invalid") or e.get("error")} if e.get("invalid") or e.get("error") else {})}))
    n = sum(not x.startswith("──") for x in lines)
    return f"{n} tool calls · {time.time() - t0:.0f} s\n\n" + "\n".join(lines[-80:])


def _render(w):
    w.call("render_final", filename="final.mp4")
    w.call("save_blend", filename="scene.blend")


def direct(request, director, ollama_url):
    if not request.strip():
        yield "Type what should happen first.", None
        return
    if ollama_url:
        os.environ["P5_OLLAMA_URL"] = ollama_url.strip()
    code = DIRECTORS[director]
    out = OUT / f"direct_{time.strftime('%H%M%S')}_{code}"

    def job(w, log):
        _agent(code).run(request, w, log=None if code == "A3" else log, task_id=None)
        state = w.call("scene_state")
        _render(w)
        return state

    for text, done, holder in _run(job, out):
        if not done:
            yield text, None
            continue
        if "error" in holder:
            yield text + f"\n\nStopped: {holder['error']}", None
            return
        secs = holder["result"]["frames"]["seconds"]
        yield text + f"\n\nDone: a {secs} s clip.", str(out / "final.mp4")


def run_task(label, director, ollama_url):
    if ollama_url:
        os.environ["P5_OLLAMA_URL"] = ollama_url.strip()
    task, code = TASK_BY_LABEL[label], DIRECTORS[director]
    defaults = TASKS["defaults"]["checks"]
    out = OUT / f"task_{task['id']}_{time.strftime('%H%M%S')}_{code}"

    def job(w, log):
        def check():
            rep = check_task(task, w.call("sample_scene"), defaults)
            return rep["passed"], report_text(rep)
        # Claude's calls are shown from its MCP log file, so it gets no log callback (no duplicates)
        stats = _agent(code, fix_rounds=3).run(task["request"], w, log=None if code == "A3" else log,
                                               check=check, task_id=task["id"])
        rep = check_task(task, w.call("sample_scene"), defaults)
        _render(w)
        return {"report": rep, "stats": stats if isinstance(stats, dict) else {}}

    for text, done, holder in _run(job, out):
        if not done:
            yield text, "Checking after the agent finishes…", None
            continue
        if "error" in holder:
            yield text, f"Stopped: {holder['error']}", None
            return
        rep = holder["result"]["report"]
        rounds = holder["result"]["stats"].get("rounds", [])
        lines = [f"## {'PASS' if rep['passed'] else 'FAIL'} — {sum(r['ok'] for r in rep['results'])}/{len(rep['results'])} checks"]
        if len(rounds) > 1:
            lines.append(f"First try: {'pass' if rounds[0]['passed'] else 'fail'}; fixed after {len(rounds) - 1} round(s) "
                         "of the checker's report." if rep["passed"] else f"Still failing after {len(rounds) - 1} fix round(s).")
        for r in rep["results"]:
            mark = "✅" if r["ok"] else "❌"
            lines.append(f"- {mark} **{r['check']}**{' (default)' if r['default'] else ''}: {r['detail']}")
        yield text, "\n".join(lines), str(out / "final.mp4")


def load_story(name):
    return (config.ROOT / "stories" / name).read_text(encoding="utf-8")


def run_story(story_json, director, ollama_url):
    from story import camera_request, shot_request
    if ollama_url:
        os.environ["P5_OLLAMA_URL"] = ollama_url.strip()
    try:
        story = json.loads(story_json)
        assert story["shots"]
    except Exception as e:
        yield f"The story isn't valid JSON with a list of shots: {e}", None
        return
    code = DIRECTORS[director]
    if code == "A0":
        yield "The template rules can't direct stories; pick Claude or qwen.", None
        return
    out = OUT / f"story_{time.strftime('%H%M%S')}_{code}"

    def job(w, log):
        w.call("scene_reset")
        agent = _agent(code)
        for k in range(len(story["shots"]) + 1):
            state = w.call("scene_state")
            last = k == len(story["shots"])
            if code != "A3":
                log("──", {"": "── camera" if last else f"── shot {k + 1}: {story['shots'][k]}"}, None)
            req = camera_request(story, state) if last else shot_request(story, k, state)
            agent.run(req, w, log=None if code == "A3" else log, task_id="camera" if last else f"shot{k + 1}",
                      reset=False)
            if k > 0:
                before = {o["name"] for o in state["objects"]}
                for o in w.call("scene_state")["objects"]:
                    if o["kind"] == "figure" and o["name"] not in before:
                        w.call("appear_at", name=o["name"], frame=state["frames"]["end"] + 1)
        _render(w)
        return w.call("scene_state")

    for text, done, holder in _run(job, out):
        if not done:
            yield text, None
            continue
        if "error" in holder:
            yield text + f"\n\nStopped: {holder['error']}", None
            return
        yield text + f"\n\nDone: {holder['result']['frames']['seconds']} s.", str(out / "final.mp4")


def _summary_md():
    rows = ["| Agent | Passed | First try | Calls / task | Invalid calls |", "|---|---|---|---|---|"]
    for a in AGENT_NAMES:
        f = RESULTS / a / "summary.json"
        if not f.exists():
            continue
        s = json.loads(f.read_text(encoding="utf-8"))
        calls = sum(t["tool_calls"] for t in s["tasks"])
        bad = sum(t["invalid_calls"] for t in s["tasks"])
        rows.append(f"| {a} · {AGENT_NAMES[a]} | **{s['passed']} / {s['total']}** | {s['passed_first']} | "
                    f"{calls / s['total']:.1f} | {100 * bad / max(calls, 1):.0f}% |")
    return "\n".join(rows)


def show_result(agent_label, task_label):
    a = agent_label.split(" ")[0]
    tid = TASK_BY_LABEL[task_label]["id"]
    f = RESULTS / a / tid / "result.json"
    if not f.exists():
        return "No saved run for this one.", "", None
    r = json.loads(f.read_text(encoding="utf-8"))
    head = f"## {'PASS' if r['passed'] else 'FAIL'}"
    if r["passed"] and not r["passed_first"]:
        head += f" (after {r['fix_rounds_used']} fix round(s) from the checker's report)"
    lines = [head, f"*{r['request']}*", "",
             f"{r['tool_calls']} tool calls, {r['invalid_calls']} invalid, {r['seconds']} s"]
    if r.get("error"):
        lines.append(f"Stopped: {r['error'][:300]}")
    for c in r["report"]["results"]:
        lines.append(f"- {'✅' if c['ok'] else '❌'} **{c['check']}**{' (default)' if c['default'] else ''}: "
                     f"{c['detail'][:300]}")
    calls = "\n".join(_line(c) for c in r["calls"])
    clip = CLIPS / a / f"{tid}.mp4"
    return "\n".join(lines), calls, str(clip) if clip.exists() else None


CSS = """
.gradio-container {max-width: 1500px !important}
#story .cm-content {white-space: pre-wrap !important; word-break: break-word}
#log textarea {font-family: 'IBM Plex Mono', Consolas, monospace; font-size: 12.5px}
"""

with gr.Blocks(title="Stick Animation Agent", css=CSS, theme=gr.themes.Soft(primary_hue="red")) as app:
    gr.Markdown("# Stick Animation Agent\nType what should happen; an agent directs it in Blender with checked "
                "tools, and the clip is rendered. " + (
                    "Here the template rules (A0) direct live, rendered by Blender on this server (CPU, so a "
                    "clip takes about a minute). The **Results** tab has every agent's final run, Claude and "
                    "qwen included: tool calls, checks and the clip rebuilt from those calls. UMC301 Project 5 "
                    "· [code](https://github.com/arcyadav/blender-stick-animation-agent)" if PUBLIC else
                    "Claude runs through MCP on this machine; qwen runs on Ollama (here or on a Kaggle GPU)."))
    with gr.Row():
        director = gr.Dropdown(list(DIRECTORS), value=list(DIRECTORS)[0], label="Director")
        ollama = gr.Textbox(value=os.environ.get("P5_OLLAMA_URL", ""), label="Ollama URL (for qwen)",
                            placeholder="empty = this laptop; or https://….trycloudflare.com", visible=not PUBLIC)
    with gr.Tab("Direct"):
        with gr.Row():
            with gr.Column(scale=5):
                request = gr.Textbox(label="What should happen", lines=3, value=EXAMPLES[0])
                gr.Examples(EXAMPLES, inputs=request)
                go = gr.Button("Direct it", variant="primary")
                log1 = gr.Textbox(label="The agent's tool calls", lines=18, elem_id="log", interactive=False)
            with gr.Column(scale=6):
                video1 = gr.Video(label="Clip", autoplay=True)
        go.click(direct, [request, director, ollama], [log1, video1])
    with gr.Tab("Results"):
        gr.Markdown("Final run, 25 Oct 2026: the same 30 tasks and tools for every agent, checked from the scene "
                    "data. Clips are rebuilt by replaying each run's own tool calls.\n\n" + _summary_md())
        with gr.Row():
            with gr.Column(scale=5):
                r_agent = gr.Dropdown([f"{a} · {n}" for a, n in AGENT_NAMES.items()], value="A3 · Claude (MCP)",
                                      label="Agent")
                r_task = gr.Dropdown(list(TASK_BY_LABEL), value=list(TASK_BY_LABEL)[18], label="Task")
                r_report = gr.Markdown()
                r_calls = gr.Textbox(label="Its tool calls", lines=12, elem_id="log", interactive=False)
            with gr.Column(scale=6):
                r_video = gr.Video(label="Clip (replayed from the calls)", autoplay=True)
        for comp in (r_agent, r_task):
            comp.change(show_result, [r_agent, r_task], [r_report, r_calls, r_video])
        app.load(show_result, [r_agent, r_task], [r_report, r_calls, r_video])
    with gr.Tab("Story", visible=not PUBLIC):
        with gr.Row():
            with gr.Column(scale=7):
                pick = gr.Dropdown(STORIES, value=STORIES[0] if STORIES else None, label="Story")
                story_box = gr.Code(value=load_story(STORIES[0]) if STORIES else "", language="json",
                                    label="Shots (edit freely)", lines=20, elem_id="story")
                go2 = gr.Button("Direct the story, shot by shot", variant="primary")
                log2 = gr.Textbox(label="Progress", lines=14, elem_id="log", interactive=False)
            with gr.Column(scale=5):
                video2 = gr.Video(label="Clip", autoplay=True)
        pick.change(load_story, pick, story_box)
        go2.click(run_story, [story_box, director, ollama], [log2, video2])
    with gr.Tab("Task + checks"):
        with gr.Row():
            with gr.Column(scale=5):
                task = gr.Dropdown(list(TASK_BY_LABEL), value=list(TASK_BY_LABEL)[18], label="One of the 30 tasks")
                go3 = gr.Button("Run with the checker and fix loop", variant="primary")
                log3 = gr.Textbox(label="The agent's tool calls", lines=12, elem_id="log", interactive=False)
                report = gr.Markdown()
            with gr.Column(scale=6):
                video3 = gr.Video(label="Clip", autoplay=True)
        go3.click(run_task, [task, director, ollama], [log3, report, video3])

SPACE = "Arcyadav/stick-animation-agent"    # the static project page; its "Live demo" section reads live.json


def announce(url):
    """Write live.json to the project page, so its Live demo section points at this run (None = offline)."""
    from datetime import datetime, timezone
    from huggingface_hub import HfApi
    info = {"url": url, "since": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        HfApi().upload_file(path_or_fileobj=json.dumps(info).encode(), path_in_repo="live.json", repo_id=SPACE,
                            repo_type="space", commit_message="live demo online" if url else "live demo offline")
        print(f"project page now shows: {url or 'offline'}")
    except Exception as e:                       # no login / no network: the demo itself still works
        print(f"could not update {SPACE}/live.json: {e}")


if __name__ == "__main__":
    if PUBLIC:
        app.queue(default_concurrency_limit=1).launch(server_name="0.0.0.0", server_port=7860,
                                                      allowed_paths=[str(CLIPS), str(OUT)])
    else:
        # --share: a public link to this laptop's app (Blender, Claude and qwen still run here), announced on
        # the project page's Live demo section while it runs
        pw = os.environ.get("P5_PASSWORD")
        _, _, share_url = app.queue(default_concurrency_limit=1).launch(
            inbrowser=True, share="--share" in sys.argv, auth=("viva", pw) if pw else None,
            allowed_paths=[str(CLIPS), str(OUT)], prevent_thread_lock=True)
        if share_url:
            print(f"public link: {share_url}")
            announce(share_url)
        try:
            app.block_thread()
        finally:
            if share_url:
                announce(None)
