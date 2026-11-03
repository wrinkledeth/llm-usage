# LLM Usage

Native macOS menu-bar app (Swift 6 / SwiftUI, macOS 26) showing subscription usage for
**Codex**, **Claude** and **OpenCode Go**. Each provider gets its logo with the 5-hour window
stacked over the weekly one; click for a panel with progress bars, reset countdowns, OpenCode
Go's monthly cap and Codex credits. Right-click for Refresh / Quit.

It refreshes every 5 minutes, after the Mac wakes, and when the panel opens with data older
than a minute. A provider that isn't set up on this Mac is hidden; one that fails keeps its last
reading (dimmed) and shows the error in the panel.

## Install

```bash
macapp install    # → /Applications/LLM Usage.app
```

It registers as a login item on first launch (toggle in the panel). Errors go to
`~/Library/Logs/LLM Usage.log`.

If a per-app firewall such as LuLu is running, allow **LLM Usage** to connect out. Menu-bar
managers (Thaw, Ice, Bartender) may put the item in their hidden section the first time.

## Where the numbers come from

| Provider | Source | Credentials |
|---|---|---|
| Claude | `claude -p … /usage` (Claude Code CLI; uses no tokens) | the CLI's own login |
| Codex | `chatgpt.com/backend-api/wham/usage`, falling back to `codex app-server` (`account/rateLimits/read`) | `~/.codex/auth.json` (or `$CODEX_HOME`); tokens are refreshed and written back like the CLI does |
| OpenCode Go | `opencode.ai/zen/go/v1/usage` | `opencode-go` API key from `OPENCODE_API_KEY`, Pi's `~/.pi/agent/auth.json`, or OpenCode's `~/.local/share/opencode/auth.json` |

`CLAUDE_CLI_PATH` / `CODEX_CLI_PATH` override where the CLIs are found (otherwise PATH plus
`/opt/homebrew/bin`, `~/.local/bin`, `/usr/local/bin`). Credentials stay on this Mac and are only
sent to the provider they belong to.

## Develop

```bash
swift build
./test.sh                                   # unit tests (Swift Testing)
macapp run                                  # debug build + launch
.build/debug/LLMUsage --print               # fetch every provider once and print
.build/debug/LLMUsage --print --codex-app-server
"/Applications/LLM Usage.app/Contents/MacOS/LLMUsage" --snapshot /tmp/shots   # render label + panel PNGs
```

Version 2.0 replaced the earlier Python/rumps app (see git history before commit `1d40089`).
It dropped the Claude browser-cookie fallback and the GitHub release check.

## Credits

- [`BOUSHABAMohammed/claude-bar`](https://github.com/BOUSHABAMohammed/claude-bar), the original Python app
- [`steipete/CodexBar`](https://github.com/steipete/CodexBar), for the Codex and OpenCode Go endpoints
- DeepSeek logo from [`lobehub/lobe-icons`](https://github.com/lobehub/lobe-icons) (MIT)

## License

MIT
