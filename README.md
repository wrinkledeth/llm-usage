# LLM Usage

Compact macOS menu bar app for Claude and Codex usage. It shows Codex on the left, Claude on the right, with stacked `5h` and `7d` percentages.

![](image-1.png)

![](image-2.png)

## Instal## Install

```bash
macapp install    # → /Applications/LLM Usage.app (shared tool, see macapp.conf)
```

`LLM Usage.app` is a small native launcher (`Sources/LLMUsage`) around the Python app.
On launch it syncs a private venv with `uv.lock` (in `~/Library/Application Support/LLM
Usage/venv`, only when the lock changes; needs `uv`), runs `claude_bar.py`, restarts it
after a crash, and stops it when the app quits. It registers itself as a login item
(toggle in System Settings › General › Login Items). Log: `~/Library/Logs/LLM Usage.log`.

Claude Code authentication is used by default, with the browser-cookie fallback.

For development:

```bash
uv sync --frozen --no-dev
.venv/bin/python claude_bar.py            # --browser firefox forces the cookie fallback
```

## Remove

Quit it from its menu, turn it off in Login Items, and delete `/Applications/LLM Usage.app`
(plus `~/Library/Application Support/LLM Usage` for the venv).
ity

- Claude usage is fetched from the authenticated Claude Code CLI's zero-token
  `/usage` command. A local `claude.ai` browser session is retained as a fallback.
- Codex usage is fetched from local Codex auth in `~/.codex/auth.json` or `$CODEX_HOME/auth.json`, with `codex app-server` fallback when needed.
- Credentials stay local and are only used to call Claude/OpenAI endpoints directly.

## Credits

- [`BOUSHABAMohammed/claude-bar`](https://github.com/BOUSHABAMohammed/claude-bar)
- [`steipete/CodexBar`](https://github.com/steipete/CodexBar)

## License

MIT
