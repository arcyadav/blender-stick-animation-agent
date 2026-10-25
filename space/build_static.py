"""Build the free static Hugging Face Space: the showcase page plus a browser for every final run.

    python space/build_static.py            # -> outputs/.site
    python space/build_static.py --upload   # also uploads to Arcyadav/stick-animation-agent

Live directing needs Blender and Claude / qwen, so it runs on the laptop (`python demo_app.py`); the site
shows the final runs: each agent's tool calls, its checks, and the clip rebuilt from those calls.
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "outputs" / ".site"
RESULTS = ROOT / "results" / "final_2026-10-25"
SHOWCASE = ROOT / "outputs" / "showcase"
CLIPS = ROOT / "outputs" / "replays"
AGENTS = {"A0": "Template rules", "A1": "qwen2.5 3b", "A2": "qwen2.5 7b", "A3": "Claude via MCP"}
REPO = "Arcyadav/stick-animation-agent"

BROWSER = """
  <section id="runs">
    <div class="head">
      <span class="eyebrow">Every run</span>
      <h2>Browse the final run</h2>
      <p>All 120 runs: four agents on the same 30 tasks. Pick an agent and a task to see the agent's tool
        calls, the checker's verdict and the clip. Each clip is rebuilt in Blender by replaying that run's
        own tool calls; all 120 replays give the same pass or fail as the recorded run.</p>
    </div>
    <div class="agents" role="tablist" id="agentTabs"></div>
    <div class="runs">
      <ol class="tasklist" id="taskList"></ol>
      <div class="detail" id="detail"></div>
    </div>
  </section>
"""

CSS = """
.agents { display: flex; flex-wrap: wrap; gap: 8px; }
.agents button { font: 500 0.85rem var(--mono); padding: 7px 12px; border-radius: 999px; border: 1px solid var(--rule);
  background: var(--sheet); color: var(--ink); cursor: pointer; }
.agents button[aria-selected="true"] { background: var(--ink); color: var(--paper); border-color: var(--ink); }
.agents button span { color: var(--pencil); margin-left: 6px; }
.agents button[aria-selected="true"] span { color: var(--paper); opacity: .75; }
.runs { display: grid; grid-template-columns: minmax(0, 330px) minmax(0, 1fr); gap: 18px; align-items: start; }
@media (max-width: 760px) { .runs { grid-template-columns: minmax(0, 1fr); } .tasklist { max-height: 260px; } }
.tasklist { list-style: none; margin: 0; padding: 0; border: 1px solid var(--rule); border-radius: 4px;
  background: var(--sheet); max-height: 640px; overflow-y: auto; }
.tasklist li button { width: 100%; text-align: left; display: grid; grid-template-columns: 2.6rem 3rem 1fr; gap: 8px;
  align-items: baseline; padding: 8px 12px; border: 0; border-bottom: 1px solid var(--rule); background: none;
  color: var(--ink); font: 0.86rem/1.35 var(--body); cursor: pointer; }
.tasklist li:last-child button { border-bottom: 0; }
.tasklist li button[aria-current="true"] { background: var(--tint); }
.tasklist code { font: 0.78rem var(--mono); color: var(--pencil); }
.mark { font: 600 0.72rem var(--mono); }
.mark.ok { color: var(--ok); } .mark.no { color: var(--ball); }
.detail { display: grid; gap: 12px; min-width: 0; }
.detail video { width: 100%; aspect-ratio: 16 / 9; border: 1px solid var(--rule); border-radius: 3px; background: #fff; }
.detail h3 { font-size: 1.2rem; }
.detail .req { font-size: 1.02rem; }
.verdict { font: 600 0.8rem var(--mono); padding: 3px 10px; border-radius: 999px; display: inline-block; }
.verdict.ok { background: var(--okTint); color: var(--ok); } .verdict.no { background: var(--tint); color: var(--ball); }
.facts { display: flex; flex-wrap: wrap; gap: 4px 18px; font: 0.82rem var(--mono); color: var(--pencil); }
.checklist { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; font-size: 0.88rem; }
.checklist li { display: grid; grid-template-columns: 1.1rem 1fr; gap: 6px; }
.checklist b { font-weight: 600; }
.checklist .dim { color: var(--pencil); }
details.calls summary { cursor: pointer; font: 500 0.85rem var(--mono); }
details.calls pre { margin: 8px 0 0; max-height: 360px; overflow: auto; background: var(--sheet); border: 1px solid var(--rule);
  border-radius: 4px; padding: 10px; font: 0.76rem/1.5 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; }
details.calls .err { color: var(--ball); }
"""

TOKENS = {  # added to the page's light / dark token blocks
    "light": "--ok: #1f7a4a; --okTint: #e6f3ec;",
    "dark": "--ok: #6fcf97; --okTint: #17291f;",
}

SCRIPT = """
<script>
(function () {
  var NAMES = %s, data = null, agent = "A3", task = "q05";
  try { var h = (location.hash || "").slice(1).split("."); if (NAMES[h[0]]) agent = h[0]; if (h[1]) task = h[1]; } catch (e) {}
  var tabs = document.getElementById("agentTabs"), list = document.getElementById("taskList"),
      detail = document.getElementById("detail");
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }
  function drawTabs() {
    tabs.innerHTML = "";
    Object.keys(NAMES).forEach(function (a) {
      var s = data.summary[a], b = document.createElement("button");
      b.setAttribute("role", "tab"); b.setAttribute("aria-selected", a === agent);
      b.innerHTML = esc(a + " · " + NAMES[a]) + "<span>" + s.passed + "/" + s.total + "</span>";
      b.onclick = function () { agent = a; draw(); };
      tabs.appendChild(b);
    });
  }
  function drawList() {
    list.innerHTML = "";
    data.tasks.forEach(function (t) {
      var r = data.runs[agent][t.id], li = document.createElement("li"), b = document.createElement("button");
      if (t.id === task) b.setAttribute("aria-current", "true");
      var mark = r.passed ? '<span class="mark ok">PASS</span>' : '<span class="mark no">FAIL</span>';
      b.innerHTML = "<code>" + t.id + "</code>" + mark + "<span>" + esc(t.request) + "</span>";
      b.onclick = function () { task = t.id; draw(); };
      li.appendChild(b); list.appendChild(li);
    });
  }
  function drawDetail() {
    var r = data.runs[agent][task], t = data.tasks.filter(function (x) { return x.id === task; })[0];
    var v = r.passed ? (r.passed_first ? "PASS" : "PASS after " + r.fix_rounds_used + " fix round" + (r.fix_rounds_used > 1 ? "s" : "")) : "FAIL";
    var checks = r.checks.map(function (c) {
      return "<li><span>" + (c.ok ? "✅" : "❌") + "</span><span><b>" + esc(c.check) + "</b>" +
        (c["default"] ? ' <span class="dim">(default)</span>' : "") + ": " + esc(c.detail) + "</span></li>";
    }).join("");
    var calls = r.calls.map(function (c) {
      return esc(c[0] + " " + c[1]) + (c[2] ? '\\n    <span class="err">✗ ' + esc(c[2]) + "</span>" : "");
    }).join("\\n");
    detail.innerHTML =
      '<video src="runs/' + agent + "/" + task + '.mp4" controls muted playsinline preload="metadata"></video>' +
      '<div><span class="verdict ' + (r.passed ? "ok" : "no") + '">' + v + "</span></div>" +
      '<p class="req">' + esc(t.request) + "</p>" +
      '<div class="facts"><span>' + esc(agent + " · " + NAMES[agent]) + "</span><span>" + r.tool_calls + " tool calls</span><span>" +
      r.invalid_calls + " invalid</span><span>" + r.seconds + " s</span></div>" +
      (r.error ? '<p class="muted">Stopped: ' + esc(r.error) + "</p>" : "") +
      '<ul class="checklist">' + checks + "</ul>" +
      '<details class="calls"><summary>The agent\\'s ' + r.calls.length + " tool calls</summary><pre>" + calls + "</pre></details>";
  }
  function draw() { drawTabs(); drawList(); drawDetail(); }
  fetch("runs/data.json").then(function (r) { return r.json(); }).then(function (d) { data = d; draw(); })
    .catch(function () { detail.innerHTML = '<p class="muted">The run data could not be loaded. Reload the page to try again.</p>'; });
})();
</script>
"""


def _short(v, n):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[:n] + "…"


def build():
    shutil.rmtree(SITE, ignore_errors=True)
    shutil.copytree(SHOWCASE, SITE)
    tasks = json.loads((ROOT / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    data = {"tasks": [{"id": t["id"], "request": t["request"]} for t in tasks], "summary": {}, "runs": {}}
    for a in AGENTS:
        data["summary"][a] = json.loads((RESULTS / a / "summary.json").read_text(encoding="utf-8"))
        data["summary"][a] = {k: data["summary"][a][k] for k in ("passed", "passed_first", "total")}
        data["runs"][a] = {}
        for t in tasks:
            r = json.loads((RESULTS / a / t["id"] / "result.json").read_text(encoding="utf-8"))
            data["runs"][a][t["id"]] = {
                **{k: r[k] for k in ("passed", "passed_first", "fix_rounds_used", "tool_calls", "invalid_calls",
                                     "seconds", "error")},
                "checks": [{"check": c["check"], "ok": c["ok"], "detail": _short(c["detail"], 400),
                            "default": c["default"]} for c in r["report"]["results"]],
                "calls": [[c["tool"], _short(c["args"], 220), _short(c["error"], 200) if c.get("error") else None]
                          for c in r["calls"]]}
            src = CLIPS / a / f"{t['id']}.mp4"
            dst = SITE / "runs" / a / f"{t['id']}.mp4"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    (SITE / "runs" / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                                             encoding="utf-8")

    page = (SITE / "index.html").read_text(encoding="utf-8")
    page = page.replace('<meta name="claude:viewport-fit-sides" content="cover">\n', "")
    head = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n')
    page = head + page.replace("</style>", CSS + "</style>\n</head>\n<body>", 1)
    page = page.replace("  --tint: #fbeeec;\n", "  --tint: #fbeeec;\n  " + TOKENS["light"] + "\n", 1)
    page = page.replace("--tint: #2a1c1a; color-scheme: dark;", "--tint: #2a1c1a; " + TOKENS["dark"] + " color-scheme: dark;")
    page = page.replace("body {\n  background", "body { margin: 0;\n  background", 1)
    page = page.replace("  <footer>", BROWSER + "\n  <footer>", 1)
    page = page.replace("this table will be updated", "")
    page += SCRIPT % json.dumps(AGENTS) + "\n</body>\n</html>\n"
    (SITE / "index.html").write_text(page, encoding="utf-8")
    shutil.copy2(ROOT / "space" / "README_static.md", SITE / "README.md")
    (SITE / ".gitattributes").write_text("*.mp4 filter=lfs diff=lfs merge=lfs -text\n")
    files = [p for p in SITE.rglob("*") if p.is_file()]
    print(f"built {len(files)} files, {sum(p.stat().st_size for p in files) / 1e6:.1f} MB -> {SITE}")


def upload():
    from huggingface_hub import HfApi
    api = HfApi()
    api.create_repo(REPO, repo_type="space", space_sdk="static", exist_ok=True)
    api.upload_folder(repo_id=REPO, repo_type="space", folder_path=str(SITE), commit_message="Update project page")
    print(f"https://huggingface.co/spaces/{REPO}  ->  https://{REPO.lower().replace('/', '-')}.static.hf.space")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    build()
    if a.upload:
        upload()
