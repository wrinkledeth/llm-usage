"""OpenCode Go subscription usage (5h rolling, weekly and monthly spend caps).

The API key is the same one Pi or OpenCode use for the `opencode-go` provider, so no
separate login is needed. Lookup order: `OPENCODE_API_KEY`, Pi's auth store, then
OpenCode's auth store.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import urllib.error
import urllib.request
from typing import Any

from usage_models import ProviderUsageSnapshot, UsageWindowSnapshot

USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
PROVIDER_KEY = "opencode-go"
ROLLING_WINDOW_SECONDS = 5 * 60 * 60
WEEKLY_WINDOW_SECONDS = 7 * 24 * 60 * 60
USER_AGENT = "llm-usage"


class OpenCodeUsageError(RuntimeError):
    pass


class OpenCodeAuthNotFoundError(OpenCodeUsageError):
    """No OpenCode Go key on this machine; the provider is hidden, not shown as an error."""


def auth_file_candidates(env: dict[str, str] | None = None) -> list[pathlib.Path]:
    env = env if env is not None else dict(os.environ)
    home = pathlib.Path(env.get("HOME") or pathlib.Path.home())
    pi_dir = pathlib.Path(env["PI_CODING_AGENT_DIR"]) if env.get("PI_CODING_AGENT_DIR") else home / ".pi" / "agent"
    data_home = pathlib.Path(env["XDG_DATA_HOME"]) if env.get("XDG_DATA_HOME") else home / ".local" / "share"
    return [pi_dir / "auth.json", data_home / "opencode" / "auth.json"]


def parse_api_key(data: Any) -> str | None:
    """Pull the opencode-go API key out of a Pi or OpenCode auth.json payload."""
    if not isinstance(data, dict):
        return None
    entry = data.get(PROVIDER_KEY)
    if not isinstance(entry, dict):
        return None
    if entry.get("type") not in (None, "api", "api_key"):
        return None
    key = entry.get("key") or entry.get("apiKey")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return None


def load_api_key(env: dict[str, str] | None = None) -> str:
    env = env if env is not None else dict(os.environ)
    if env.get("OPENCODE_API_KEY", "").strip():
        return env["OPENCODE_API_KEY"].strip()
    for path in auth_file_candidates(env):
        try:
            key = parse_api_key(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
        if key:
            return key
    raise OpenCodeAuthNotFoundError("No OpenCode Go API key found")


def fetch_usage(api_key: str, timeout: float = 15.0) -> dict[str, Any]:
    request = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise OpenCodeUsageError("OpenCode Go key rejected (HTTP %d)" % exc.code) from exc
        raise OpenCodeUsageError(f"OpenCode Go usage HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise OpenCodeUsageError(f"OpenCode Go usage unreachable: {exc.reason}") from exc


def map_usage_snapshot(data: dict[str, Any]) -> ProviderUsageSnapshot:
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict) or not isinstance(usage.get("rolling"), dict):
        raise OpenCodeUsageError("OpenCode Go usage response missing fields")
    return ProviderUsageSnapshot(
        provider_id="opencode",
        display_name="OpenCode Go",
        session=_window(usage.get("rolling"), ROLLING_WINDOW_SECONDS),
        weekly=_window(usage.get("weekly"), WEEKLY_WINDOW_SECONDS),
        monthly=_window(usage.get("monthly"), None),
        last_updated=dt.datetime.now(dt.timezone.utc),
    )


def load_opencode_snapshot(env: dict[str, str] | None = None) -> ProviderUsageSnapshot:
    return map_usage_snapshot(fetch_usage(load_api_key(env)))


def _window(raw: Any, window_seconds: int | None) -> UsageWindowSnapshot | None:
    if not isinstance(raw, dict):
        return None
    percent = _as_float(raw.get("percent"))
    if percent is None:
        used, limit = _as_float(raw.get("used")), _as_float(raw.get("limit"))
        if used is not None and limit:
            percent = used / limit * 100
    return UsageWindowSnapshot(
        percent=percent,
        resets_at=_parse_iso(raw.get("resetsAt")),
        window_seconds=window_seconds,
    )


def _as_float(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _parse_iso(raw: Any) -> dt.datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
