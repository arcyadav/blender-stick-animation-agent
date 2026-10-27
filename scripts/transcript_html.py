"""Turn the Claude Code session into one standalone HTML page: every message I typed is Turn 1, 2, 3…,
and Claude's response sits under it in a collapsed block (with the tools it used).

    python -m scripts.transcript_html                       # this project's session log -> transcript.html
    python -m scripts.transcript_html path/to/session.jsonl out.html
    python -m scripts.transcript_html --until 165            # stop after turn 165

It reads Claude Code's session log (.jsonl), which keeps every sitting; `/export transcript.md` only
keeps the part after the last time the conversation was condensed.
"""
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
LOG = Path.home() / ".claude" / "projects" / "C--Users-ysarc-projects-aids-project-5" / \
    "792bf50d-07cf-4bd6-983e-56a53616bb6a.jsonl"

TAGS = re.compile(r"</?(pasted_content|command-message|command-args)[^>]*>")
DROP = re.compile(r"<(system-reminder|local-command-caveat|local-command-stdout|local-command-stderr)>.*?</\1>", re.S)


def user_text(content):
    """The text the person typed, or None for tool results and system messages."""
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return None
    m = re.search(r"<command-name>(.*?)</command-name>.*?<command-args>(.*?)</command-args>", content, re.S)
    if m:                                               # a slash command, e.g. /export transcript.md
        return f"{m.group(1).strip()} {m.group(2).strip()}".strip()
    text = TAGS.sub("", DROP.sub("", content)).strip()
    if not text or text.startswith(("This session is being continued", "Caveat:", "[Request interrupted")):
        return None
    return text


def load(path):
    turns = []                                          # {"when", "text", "reply": [...], "tools": [...]}
    tool_names, seen = {}, set()
    for line in open(path, encoding="utf-8"):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = e.get("type")
        if t == "user" and not e.get("isMeta") and not e.get("isCompactSummary"):
            content = e.get("message", {}).get("content")
            text = user_text(content)
            if text:
                turns.append({"when": e.get("timestamp"), "text": text, "reply": [], "tools": []})
            elif isinstance(content, list) and turns:
                for b in content:                       # the person's answers to Claude's questions
                    if isinstance(b, dict) and b.get("type") == "tool_result" and \
                            tool_names.get(b.get("tool_use_id")) == "AskUserQuestion":
                        c = b.get("content")
                        c = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [])
                        turns[-1]["reply"].append(f"*Answer:* {c.strip()[:1500]}")
        elif t == "attachment":                         # a message typed while Claude was working
            a = e.get("attachment", {})
            if a.get("type") == "queued_command" and a.get("humanTurn") and a.get("prompt"):
                turns.append({"when": a.get("timestamp") or e.get("timestamp"), "text": a["prompt"].strip(),
                              "reply": [], "tools": [], "mid": True})
        elif t == "assistant" and turns:
            msg = e.get("message", {})
            for i, b in enumerate(msg.get("content") or []):
                key = (msg.get("id"), i, b.get("type"), (b.get("text") or "")[:80], b.get("id"))
                if key in seen:
                    continue
                seen.add(key)
                if b.get("type") == "text" and b.get("text", "").strip():
                    turns[-1]["reply"].append(b["text"].strip())
                elif b.get("type") == "tool_use":
                    tool_names[b.get("id")] = b.get("name")
                    inp = b.get("input") or {}
                    what = inp.get("description") or inp.get("file_path") or inp.get("query") or \
                        inp.get("action") or inp.get("pattern") or ""
                    turns[-1]["tools"].append((b.get("name"), str(what)[:160]))
    return turns


CSS = """
:root { --bg:#f6f7f9; --card:#fff; --ink:#1b1d22; --muted:#626a75; --rule:#dde1e6; --accent:#c8372d;
  --code:#f0f2f5; --you:#eef3fb; }
@media (prefers-color-scheme: dark) { :root { --bg:#121417; --card:#1a1d21; --ink:#e8e9ec; --muted:#9aa1ab;
  --rule:#2c3036; --accent:#ef6a5c; --code:#23272d; --you:#1d2530; color-scheme: dark; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.6 "Segoe UI", system-ui, sans-serif; }
.wrap { max-width: 980px; margin: 0 auto; padding: 32px 16px 80px; }
h1 { font-size: 1.7rem; margin: 0 0 4px; } .sub { color: var(--muted); margin: 0 0 18px; }
.bar { position: sticky; top: 0; background: var(--bg); padding: 10px 0; display: flex; gap: 8px; flex-wrap: wrap;
  z-index: 2; border-bottom: 1px solid var(--rule); margin-bottom: 18px; }
.bar button, .bar input { font: inherit; padding: 6px 12px; border: 1px solid var(--rule); border-radius: 6px;
  background: var(--card); color: var(--ink); }
.bar button { cursor: pointer; } .bar input { flex: 1; min-width: 180px; }
.day { margin: 28px 0 10px; font-weight: 600; color: var(--muted); text-transform: uppercase; font-size: .8rem;
  letter-spacing: .08em; }
.turn { background: var(--card); border: 1px solid var(--rule); border-radius: 8px; margin: 10px 0; }
.turn header { display: flex; gap: 10px; align-items: baseline; padding: 10px 14px 0; }
.turn .n { font-weight: 700; color: var(--accent); white-space: nowrap; }
.turn .t { color: var(--muted); font-size: .8rem; white-space: nowrap; }
.turn .mid { color: var(--muted); font-size: .75rem; border: 1px solid var(--rule); border-radius: 99px; padding: 0 8px; }
.you { background: var(--you); margin: 8px 14px; padding: 8px 12px; border-radius: 6px; white-space: pre-wrap;
  overflow-wrap: anywhere; }
details { margin: 0 14px 12px; } summary { cursor: pointer; color: var(--muted); font-size: .9rem; }
details[open] summary { margin-bottom: 6px; }
.reply { border-left: 3px solid var(--rule); padding-left: 12px; overflow-wrap: anywhere; }
.reply pre { background: var(--code); padding: 10px; border-radius: 6px; overflow-x: auto; font-size: .85rem; }
.reply code { background: var(--code); padding: 1px 4px; border-radius: 4px; font-size: .88em; }
.reply pre code { padding: 0; background: none; }
.reply table { border-collapse: collapse; display: block; overflow-x: auto; font-size: .9rem; }
.reply th, .reply td { border: 1px solid var(--rule); padding: 4px 8px; text-align: left; }
.tools { color: var(--muted); font-size: .82rem; margin-top: 8px; }
.tools ul { margin: 4px 0; padding-left: 18px; }
.hidden { display: none; }
"""

JS = """
const all = (o) => document.querySelectorAll('details.r').forEach(d => d.open = o);
document.getElementById('open').onclick = () => all(true);
document.getElementById('close').onclick = () => all(false);
document.getElementById('q').oninput = (e) => {
  const q = e.target.value.toLowerCase();
  document.querySelectorAll('.turn').forEach(t => t.classList.toggle('hidden', q && !t.textContent.toLowerCase().includes(q)));
};
"""


def render(turns, title):
    md = markdown.Markdown(extensions=["fenced_code", "tables", "sane_lists"])
    out, day = [], None
    for k, t in enumerate(turns, 1):
        when = datetime.fromisoformat(t["when"].replace("Z", "+00:00")).astimezone() if t.get("when") else None
        d = when.strftime("%A %d %B %Y") if when else ""
        if d != day:
            out.append(f'<div class="day">{d}</div>')
            day = d
        reply = "\n\n".join(t["reply"]) or "*(no text reply; tools only)*"
        md.reset()
        body = md.convert(reply)
        tools = ""
        if t["tools"]:
            items = "".join(f"<li><b>{html.escape(n)}</b> {html.escape(w)}</li>" for n, w in t["tools"])
            tools = f'<div class="tools">{len(t["tools"])} tool call(s):<ul>{items}</ul></div>'
        mid = '<span class="mid">sent while Claude was working</span>' if t.get("mid") else ""
        out.append(
            f'<article class="turn" id="turn-{k}"><header><span class="n">Turn {k}</span>'
            f'<span class="t">{when.strftime("%H:%M") if when else ""}</span>{mid}</header>'
            f'<div class="you">{html.escape(t["text"])}</div>'
            f'<details class="r"><summary>Claude\'s response</summary><div class="reply">{body}{tools}</div>'
            f'</details></article>')
    first = turns[0]["when"][:10] if turns else ""
    last = turns[-1]["when"][:10] if turns else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>'
            f'<style>{CSS}</style></head><body><div class="wrap"><h1>{html.escape(title)}</h1>'
            f'<p class="sub">Claude Code session, {first} to {last}: {len(turns)} turns. Click a turn to open '
            f'Claude\'s response.</p><div class="bar"><button id="open">Expand all</button>'
            f'<button id="close">Collapse all</button><input id="q" placeholder="Search turns…"></div>'
            + "\n".join(out) + f'</div><script>{JS}</script></body></html>')


if __name__ == "__main__":
    args = sys.argv[1:]
    until = None
    if "--until" in args:
        k = args.index("--until")
        until = int(args[k + 1])
        del args[k:k + 2]
    src = Path(args[0]) if len(args) > 0 else LOG
    dst = Path(args[1]) if len(args) > 1 else ROOT / "transcript.html"
    turns = load(src)[:until]
    dst.write_text(render(turns, "UMC301 Project 5 · Stick Animation Agent · Transcript"), encoding="utf-8")
    print(f"{len(turns)} turns -> {dst} ({dst.stat().st_size / 1e6:.1f} MB)")
