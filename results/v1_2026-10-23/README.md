# Results v1 (22–23 Oct 2026): first full comparison

System version: the 2D world with walks, run, wave, idle, look_down, react (before the handshake,
pick_up / put_down, the sad-walk head bow, hanging look-down arms and the ball's final roll).
A0 scored 30/30 on this version too (its results were overwritten by the re-run on v2).

- `tables.md`: summary, per-category and most-failed checks (`python -m scripts.results`)
- `<agent>/<task>/result.json`: the full report, every tool call, the model transcript
- `A3/claude_runs/<task>/`: Claude's MCP call log and `claude -p` output
- `A1_cpu_trial/`: the first qwen 3b trial on the laptop CPU (3 tasks, 3.5-9.5 min each)

| agent | model | where | passed | first try |
|---|---|---|---|---|
| A1 | qwen2.5:3b | Ollama on a Kaggle T4 GPU | 2/30 | 2 |
| A2 | qwen2.5:7b | Ollama on a Kaggle T4 GPU | 8/30 | 8 |
| A3 | Claude (claude -p, MCP) | subscription | 30/30 | 27 |

Fixes made during this run (they apply to every agent): default object names, `{x, z}` points accepted with
a warning, a repeat guard that only counts calls that worked, streamed Ollama replies capped at 1500 tokens
(the Cloudflare tunnel cut silent requests at 100 s).
