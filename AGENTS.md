# Repository Guidelines

## Layout
- `Sources/LLMUsageCore/`: providers and parsing, no AppKit. `ClaudeUsage` (CLI `/usage`),
  `CodexUsage` + `CodexAppServer` (OAuth usage API, JSON-RPC fallback), `OpenCodeUsage`, plus
  `ProcessRunner` (CLI lookup/PATH for launchd-started apps), `JSONValue`, `UsageFormat`.
  `ProviderID.loadUsage()` is the single entry point per provider. Throw
  `UsageError.notConfigured` when a provider isn't set up on this Mac: the UI hides it.
- `Sources/LLMUsage/`: the app. `App/UsageStore` (`@Observable`, parallel refresh, 5-min loop,
  wake refresh), `App/StatusItemController` (NSStatusItem hosting `StatusLabel`; borderless menu-material `NSPanel`
  hosting `UsagePanel`), `UI/` SwiftUI views, `App/DebugPrint` (`--print`, `--snapshot DIR`).
- `Resources/Icons/<provider id>.{svg,png}`: template logos, copied into the bundle by
  `RESOURCES` in `macapp.conf`. macOS's SVG renderer can't parse packed arc flags (`0 01-1.7`);
  keep path flags space-separated.
- `Tests/LLMUsageCoreTests/`: Swift Testing, no network.

## Commands
- `swift build`, `./test.sh` (adds the Command Line Tools' Testing.framework paths; plain
  `swift test` can't find `Testing` without Xcode).
- `macapp install` builds, signs and installs `/Applications/LLM Usage.app`; `macapp run` for a debug run.
- `.build/debug/LLMUsage --print` checks every provider live. LuLu blocks network access for new
  binaries until allowed, so URLSession requests from fresh builds time out; the installed app
  is the one allowed.

## Conventions
- Swift 6 language mode, strict concurrency; UI types are `@MainActor`, Core is `Sendable`.
- Keep parsing pure and covered by tests; avoid live network calls in tests.
- The repo dir is case-insensitive: `tests/` and `Tests/` are the same folder.
- Commit subjects use conventional style (`feat:`, `fix:` …).
