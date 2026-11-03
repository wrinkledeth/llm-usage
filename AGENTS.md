# Repository Guidelines

## Project Structure & Module Organization
- `claude_bar.py` is the menu bar entrypoint and UI coordinator. Keep AppKit updates on the main thread and push network or CLI work into background threads.
- Provider-specific logic lives beside the app: `codex_usage.py` handles Codex OAuth and app-server fallback, `color_utils.py` owns attributed menu styling, `status_image.py` renders the compact menu bar image, and `repo_metadata.py` resolves repo/update metadata.
- Put automated tests in `tests/`. Static assets such as the Claude icon and screenshots stay at the repo root unless a dedicated `assets/` directory is introduced.

## Build, Test, and Development Commands
- `uv sync --frozen --no-dev`: create the local virtualenv and install runtime dependencies.
- `.venv/bin/python claude_bar.py`: launch the menu bar app directly for local development.
- `.venv/bin/python -m unittest discover -s tests`: run the stdlib test suite.
- `macapp install`: install/update path; builds `LLM Usage.app` (native launcher in `Sources/LLMUsage` + the Python sources) into /Applications. The launcher syncs a venv from `uv.lock` and registers a login item.

## Coding Style & Naming Conventions
- Use Python 3.12, 4-space indentation, and PEP 8 naming (`snake_case` for functions/modules, `CamelCase` for classes).
- Keep provider parsing logic pure where possible so it can be unit-tested without AppKit or network access.
- Prefer small helper modules over expanding `claude_bar.py` with provider-specific branches.

## Testing Guidelines
- Add `unittest` coverage for parsing, repo metadata resolution, and provider normalization.
- Name test files `test_<feature>.py` and keep assertions deterministic; avoid live network calls in tests.
- For UI changes, verify menu bar rendering, dropdown sections, refresh flow, and degraded states on macOS.

## Commit & Pull Request Guidelines
- Recent history uses concise conventional-style subjects such as `fix: ...`; keep that format for new commits.
- PRs should explain user-visible changes, list commands run, and include screenshots when the menu bar or dropdown UI changes.

## Release & Repo Notes
- This repo is published independently. Keep `origin` pointed at your repo and add the upstream project as `upstream` for syncs.
- If you republish under a new slug, set `CLAUDE_BAR_GITHUB_REPO=owner/repo` so release checks point at the correct repository.
- Validate install behavior with `macapp install` and the log at `~/Library/Logs/LLM Usage.log`.
