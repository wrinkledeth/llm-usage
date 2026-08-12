# Claude + Codex Bar

Compact macOS menu bar app for Claude and Codex usage. It shows Codex on the left, Claude on the right, with stacked `5h` and `7d` percentages.

![](image-1.png)

![](image-2.png)

## Install

```bash
git clone git@github.com:wrinkledeth/claude-codex-bar.git
cd claude-codex-bar
./install.sh
```

`./install.sh` will prompt to add `~/Library/LaunchAgents/com.user.claude-bar.plist` for start at login.
`./uninstall.sh` unloads and removes it.

Manual control:

```bash
launchctl load ~/Library/LaunchAgents/com.user.claude-bar.plist
launchctl unload ~/Library/LaunchAgents/com.user.claude-bar.plist
```

## Run

```bash
~/.local/share/claude-bar/run.sh
```

Claude Code authentication is used by default. Force the browser-cookie fallback with
`~/.local/share/claude-bar/run.sh --browser firefox`.

For development:

```bash
uv sync --frozen --no-dev
.venv/bin/python claude_bar.py
```

## Remove

```bash
./uninstall.sh
```

## Security

- Claude usage is fetched from the authenticated Claude Code CLI's zero-token
  `/usage` command. A local `claude.ai` browser session is retained as a fallback.
- Codex usage is fetched from local Codex auth in `~/.codex/auth.json` or `$CODEX_HOME/auth.json`, with `codex app-server` fallback when needed.
- Credentials stay local and are only used to call Claude/OpenAI endpoints directly.

## Credits

- [`BOUSHABAMohammed/claude-bar`](https://github.com/BOUSHABAMohammed/claude-bar)
- [`steipete/CodexBar`](https://github.com/steipete/CodexBar)

## License

MIT
