from __future__ import annotations

import os
import pathlib
import re
import subprocess
from collections.abc import Mapping

DEFAULT_GITHUB_REPO = "BOUSHABAMohammed/claude-bar"
_GITHUB_REPO_RE = re.compile(
    r"(?:github\.com[:/]|^)(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?$"
)


def parse_github_repo(value: str | None) -> str | None:
    if not value:
        return None
    match = _GITHUB_REPO_RE.search(value.strip())
    if not match:
        return None
    return f"{match.group('owner')}/{match.group('repo')}"


def resolve_github_repo(
    repo_root: pathlib.Path | None = None,
    env: Mapping[str, str] | None = None,
    default: str = DEFAULT_GITHUB_REPO,
) -> str:
    env = env or os.environ
    override = parse_github_repo(env.get("CLAUDE_BAR_GITHUB_REPO"))
    if override:
        return override

    root = repo_root or pathlib.Path(__file__).resolve().parent
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return default

    remote = parse_github_repo(result.stdout.strip())
    return remote or default


def github_releases_url(repo: str) -> str:
    return f"https://github.com/{repo}/releases"
