from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import pwd
import re
import shutil
import subprocess
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from usage_models import ProviderUsageSnapshot, UsageWindowSnapshot

CLAUDE_CLI_PATH_ENV = "CLAUDE_CLI_PATH"
CLAUDE_USAGE_ARGS = (
    "-p",
    "--output-format",
    "json",
    "--tools",
    "",
    "--no-session-persistence",
    "/usage",
)
_SESSION_LINE = re.compile(
    r"^Current session:\s*(?P<percent>\d+(?:\.\d+)?)% used"
    r"(?:\s*(?:\u00b7|-)\s*resets\s+(?P<reset>.+))?$"
)
_WEEK_LINE = re.compile(
    r"^Current week(?: \(all models\))?:\s*(?P<percent>\d+(?:\.\d+)?)% used"
    r"(?:\s*(?:\u00b7|-)\s*resets\s+(?P<reset>.+))?$"
)
_RESET_TIME = re.compile(
    r"^(?P<date>[A-Z][a-z]{2} \d{1,2}(?:,? \d{4})?|Today|Tomorrow) at "
    r"(?P<time>\d{1,2}(?::\d{2})?[ap]m) \((?P<timezone>[^)]+)\)$",
    re.IGNORECASE,
)


class ClaudeUsageError(RuntimeError):
    pass


def load_claude_cli_snapshot(
    env: dict[str, str] | None = None,
    now: dt.datetime | None = None,
) -> ProviderUsageSnapshot:
    environment = dict(os.environ) if env is None else env
    environment = dict(environment)
    username = pwd.getpwuid(os.getuid()).pw_name
    environment.setdefault("USER", username)
    environment.setdefault("LOGNAME", username)
    executable = _resolve_claude_executable(environment)
    try:
        result = subprocess.run(
            [executable, *CLAUDE_USAGE_ARGS],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ClaudeUsageError(f"Claude CLI usage command failed: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if detail:
            detail = detail.splitlines()[-1][:160]
            raise ClaudeUsageError(f"Claude CLI usage command failed: {detail}")
        raise ClaudeUsageError(
            f"Claude CLI usage command exited with status {result.returncode}."
        )

    payload = _last_json_object(result.stdout)
    if payload.get("is_error"):
        raise ClaudeUsageError(str(payload.get("result") or "Claude CLI reported an error."))
    usage_text = payload.get("result")
    if not isinstance(usage_text, str):
        raise ClaudeUsageError("Claude CLI usage response did not include text output.")
    if usage_text.startswith("Total cost:"):
        raise ClaudeUsageError("Claude CLI could not access subscription usage.")
    return parse_claude_usage_text(usage_text, now=now)


def parse_claude_usage_text(
    usage_text: str,
    now: dt.datetime | None = None,
) -> ProviderUsageSnapshot:
    current = now or dt.datetime.now(dt.timezone.utc)
    session = None
    weekly = None

    for raw_line in usage_text.splitlines():
        line = raw_line.strip()
        session_match = _SESSION_LINE.match(line)
        if session_match:
            session = _window_from_match(session_match, 5 * 60 * 60, current)
            continue

        week_match = _WEEK_LINE.match(line)
        if week_match:
            weekly = _window_from_match(week_match, 7 * 24 * 60 * 60, current)

    if session is None or weekly is None:
        raise ClaudeUsageError("Claude CLI returned an unexpected /usage format.")

    return ProviderUsageSnapshot(
        provider_id="claude",
        display_name="Claude",
        session=session,
        weekly=weekly,
        last_updated=dt.datetime.now(dt.timezone.utc),
    )


def _last_json_object(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ClaudeUsageError("Claude CLI usage command returned invalid JSON.")


def _window_from_match(
    match: re.Match[str],
    window_seconds: int,
    now: dt.datetime,
) -> UsageWindowSnapshot:
    reset_text = match.group("reset")
    return UsageWindowSnapshot(
        percent=float(match.group("percent")),
        resets_at=_parse_reset_time(reset_text, now) if reset_text else None,
        window_seconds=window_seconds,
    )


def _parse_reset_time(value: str, now: dt.datetime) -> dt.datetime:
    match = _RESET_TIME.match(value.strip())
    if match is None:
        raise ClaudeUsageError(f"Claude CLI returned an unknown reset time: {value}")

    try:
        timezone = ZoneInfo(match.group("timezone"))
    except ZoneInfoNotFoundError as exc:
        raise ClaudeUsageError(
            f"Claude CLI returned an unknown timezone: {match.group('timezone')}"
        ) from exc

    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    local_now = now.astimezone(timezone)
    date_text = match.group("date")
    lowered_date = date_text.lower()
    if lowered_date == "today":
        reset_date = local_now.date()
    elif lowered_date == "tomorrow":
        reset_date = local_now.date() + dt.timedelta(days=1)
    else:
        reset_date = _parse_calendar_date(date_text, local_now)

    time_text = match.group("time").lower()
    time_format = "%I:%M%p" if ":" in time_text else "%I%p"
    reset_time = dt.datetime.strptime(time_text, time_format).time()
    return dt.datetime.combine(reset_date, reset_time, tzinfo=timezone)


def _parse_calendar_date(value: str, local_now: dt.datetime) -> dt.date:
    normalized = value.replace(",", "")
    parts = normalized.split()
    has_year = len(parts) == 3
    candidate = dt.datetime.strptime(
        normalized if has_year else f"{normalized} {local_now.year}",
        "%b %d %Y",
    ).date()
    if not has_year and candidate < local_now.date() - dt.timedelta(days=1):
        candidate = candidate.replace(year=candidate.year + 1)
    return candidate


def _resolve_claude_executable(env: dict[str, str]) -> str:
    search_path = env.get("PATH", "")
    override = (env.get(CLAUDE_CLI_PATH_ENV) or "").strip()
    if override:
        resolved = shutil.which(override, path=search_path)
        if resolved:
            return resolved
        raise ClaudeUsageError(f"Claude CLI not found at {override}.")

    resolved = shutil.which("claude", path=search_path)
    if resolved:
        return resolved

    home = pathlib.Path(env.get("HOME") or pathlib.Path.home())
    for candidate in (
        pathlib.Path("/opt/homebrew/bin/claude"),
        pathlib.Path("/usr/local/bin/claude"),
        home / ".local" / "bin" / "claude",
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise ClaudeUsageError(
        f"Claude CLI not found. Set {CLAUDE_CLI_PATH_ENV} or install Claude Code in PATH."
    )
