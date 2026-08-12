from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import select
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from usage_models import CreditsSnapshot, ProviderUsageSnapshot, UsageWindowSnapshot

DEFAULT_USAGE_BASE_URL = "https://chatgpt.com/backend-api/"
CHATGPT_USAGE_PATH = "/wham/usage"
CODEX_USAGE_PATH = "/api/codex/usage"
TOKEN_REFRESH_INTERVAL = dt.timedelta(days=8)
TOKEN_REFRESH_URL = "https://auth.openai.com/oauth/token"
TOKEN_REFRESH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_RPC_ARGS = ["-s", "read-only", "-a", "untrusted", "app-server"]
CODEX_CLI_PATH_ENV = "CODEX_CLI_PATH"


class CodexUsageError(RuntimeError):
    pass


class CodexAuthNotFoundError(CodexUsageError):
    pass


class CodexUnauthorizedError(CodexUsageError):
    pass


class CodexRPCError(CodexUsageError):
    pass


@dataclass(slots=True)
class CodexCredentials:
    access_token: str
    refresh_token: str
    id_token: str | None
    account_id: str | None
    last_refresh: dt.datetime | None

    @property
    def needs_refresh(self) -> bool:
        if not self.refresh_token:
            return False
        if self.last_refresh is None:
            return True
        last_refresh = self.last_refresh
        if last_refresh.tzinfo is None:
            last_refresh = last_refresh.replace(tzinfo=dt.timezone.utc)
        return dt.datetime.now(dt.timezone.utc) - last_refresh > TOKEN_REFRESH_INTERVAL


def parse_auth_data(data: bytes) -> CodexCredentials:
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise CodexUsageError(f"Invalid Codex auth.json: {exc}") from exc

    api_key = (payload.get("OPENAI_API_KEY") or "").strip()
    if api_key:
        return CodexCredentials(
            access_token=api_key,
            refresh_token="",
            id_token=None,
            account_id=None,
            last_refresh=None,
        )

    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        raise CodexUsageError("Codex auth.json exists but contains no tokens.")

    access_token = _coalesce_token(tokens, "access_token", "accessToken")
    refresh_token = _coalesce_token(tokens, "refresh_token", "refreshToken")
    if not access_token:
        raise CodexUsageError("Codex auth.json exists but contains no tokens.")

    return CodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token or "",
        id_token=_coalesce_token(tokens, "id_token", "idToken"),
        account_id=_coalesce_token(tokens, "account_id", "accountId"),
        last_refresh=_parse_iso_datetime(payload.get("last_refresh")),
    )


def auth_file_path(env: dict[str, str] | None = None) -> pathlib.Path:
    env = env or os.environ
    codex_home = (env.get("CODEX_HOME") or "").strip()
    if codex_home:
        return pathlib.Path(codex_home).expanduser() / "auth.json"
    return pathlib.Path.home() / ".codex" / "auth.json"


def load_credentials(env: dict[str, str] | None = None) -> CodexCredentials:
    path = auth_file_path(env)
    if not path.exists():
        raise CodexAuthNotFoundError("Codex auth.json not found. Run `codex login` first.")
    return parse_auth_data(path.read_bytes())


def save_credentials(credentials: CodexCredentials, env: dict[str, str] | None = None) -> None:
    path = auth_file_path(env)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            existing = {}

    existing_tokens = existing.get("tokens")
    tokens = dict(existing_tokens) if isinstance(existing_tokens, dict) else {}
    tokens["access_token"] = credentials.access_token
    tokens["refresh_token"] = credentials.refresh_token
    if credentials.id_token:
        tokens["id_token"] = credentials.id_token
    if credentials.account_id:
        tokens["account_id"] = credentials.account_id

    existing["tokens"] = tokens
    existing["last_refresh"] = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")


def resolve_usage_url(env: dict[str, str] | None = None, config_contents: str | None = None) -> str:
    env = env or os.environ
    base_url = _resolve_chatgpt_base_url(env=env, config_contents=config_contents)
    normalized = _normalize_chatgpt_base_url(base_url)
    path = CHATGPT_USAGE_PATH if "/backend-api" in normalized else CODEX_USAGE_PATH
    return normalized + path


def refresh_credentials(credentials: CodexCredentials) -> CodexCredentials:
    if not credentials.refresh_token:
        return credentials

    request = urllib.request.Request(
        TOKEN_REFRESH_URL,
        data=json.dumps(
            {
                "client_id": TOKEN_REFRESH_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": credentials.refresh_token,
            }
        ).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        if exc.code == 401:
            code = _extract_refresh_error_code(body)
            if code:
                raise CodexUnauthorizedError(
                    f"Codex refresh token invalid ({code}). Run `codex login` again."
                ) from exc
            raise CodexUnauthorizedError("Codex refresh token expired. Run `codex login` again.") from exc
        raise CodexUsageError(f"Codex token refresh failed with HTTP {exc.code}.") from exc
    except Exception as exc:
        raise CodexUsageError(f"Codex token refresh failed: {exc}") from exc

    return CodexCredentials(
        access_token=payload.get("access_token") or credentials.access_token,
        refresh_token=payload.get("refresh_token") or credentials.refresh_token,
        id_token=payload.get("id_token") or credentials.id_token,
        account_id=credentials.account_id,
        last_refresh=dt.datetime.now(dt.timezone.utc),
    )


def fetch_oauth_usage(credentials: CodexCredentials, env: dict[str, str] | None = None) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {credentials.access_token}",
        "Accept": "application/json",
        "User-Agent": "claude-codex-bar",
    }
    if credentials.account_id:
        headers["ChatGPT-Account-Id"] = credentials.account_id

    request = urllib.request.Request(
        resolve_usage_url(env),
        headers=headers,
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        if exc.code in (401, 403):
            raise CodexUnauthorizedError("Codex OAuth token expired or invalid.") from exc
        raise CodexUsageError(_format_http_error("Codex usage API", exc.code, body)) from exc
    except Exception as exc:
        raise CodexUsageError(f"Codex usage fetch failed: {exc}") from exc


def map_codex_oauth_snapshot(data: dict[str, Any]) -> ProviderUsageSnapshot:
    rate_limit = data.get("rate_limit")
    if not isinstance(rate_limit, dict):
        raise CodexUsageError("Codex usage response did not include rate limits.")

    session, weekly = _split_codex_windows(
        [
            _window_from_usage_payload(rate_limit.get("primary_window")),
            _window_from_usage_payload(rate_limit.get("secondary_window")),
        ]
    )
    if session is None and weekly is None:
        raise CodexUsageError("Codex usage response did not include rate limits.")

    credits_payload = data.get("credits")
    credits = None
    if isinstance(credits_payload, dict):
        has_credits = bool(credits_payload.get("has_credits"))
        unlimited = bool(credits_payload.get("unlimited"))
        balance = _as_float(credits_payload.get("balance"))
        if has_credits or unlimited or (balance is not None and balance > 0):
            credits = CreditsSnapshot(
                kind="codex_balance",
                enabled=True,
                unlimited=unlimited,
                balance=balance,
            )

    return ProviderUsageSnapshot(
        provider_id="codex",
        display_name="Codex",
        session=session,
        weekly=weekly,
        credits=credits,
        last_updated=dt.datetime.now(dt.timezone.utc),
    )


def map_codex_rpc_snapshot(_account_payload: dict[str, Any], rate_limits_payload: dict[str, Any]) -> ProviderUsageSnapshot:
    limits = _select_rpc_rate_limits(rate_limits_payload)
    if not isinstance(limits, dict):
        raise CodexRPCError("Codex app-server returned no rate limits.")

    session, weekly = _split_codex_windows(
        [
            _window_from_rpc_payload(limits.get("primary")),
            _window_from_rpc_payload(limits.get("secondary")),
        ]
    )
    if session is None and weekly is None:
        raise CodexRPCError("Codex app-server returned no rate limits.")

    credits_payload = limits.get("credits")
    credits = None
    if isinstance(credits_payload, dict):
        balance = _as_float(credits_payload.get("balance"))
        has_credits = bool(credits_payload.get("hasCredits"))
        unlimited = bool(credits_payload.get("unlimited"))
        if has_credits or unlimited or (balance is not None and balance > 0):
            credits = CreditsSnapshot(
                kind="codex_balance",
                enabled=True,
                unlimited=unlimited,
                balance=balance,
            )

    return ProviderUsageSnapshot(
        provider_id="codex",
        display_name="Codex",
        session=session,
        weekly=weekly,
        credits=credits,
        last_updated=dt.datetime.now(dt.timezone.utc),
    )


def load_codex_snapshot(env: dict[str, str] | None = None) -> ProviderUsageSnapshot:
    env = env or dict(os.environ)
    oauth_error: Exception | None = None

    try:
        credentials = load_credentials(env)
        if credentials.needs_refresh:
            credentials = refresh_credentials(credentials)
            save_credentials(credentials, env)

        try:
            return map_codex_oauth_snapshot(fetch_oauth_usage(credentials, env))
        except CodexUnauthorizedError:
            refreshed = refresh_credentials(credentials)
            save_credentials(refreshed, env)
            return map_codex_oauth_snapshot(fetch_oauth_usage(refreshed, env))
    except Exception as exc:
        oauth_error = exc

    try:
        account_payload, rate_limits_payload = fetch_rpc_snapshot(env)
        return map_codex_rpc_snapshot(account_payload, rate_limits_payload)
    except Exception as rpc_error:
        if oauth_error is None:
            raise
        raise CodexUsageError(
            f"{_short_error(oauth_error)}; app-server fallback failed: {_short_error(rpc_error)}"
        ) from rpc_error


def fetch_rpc_snapshot(env: dict[str, str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    client = _CodexRPCClient(env=env or dict(os.environ))
    try:
        client.initialize()
        account_payload = client.request("account/read", {})
        rate_limits_payload = client.request("account/rateLimits/read")
        return account_payload, rate_limits_payload
    finally:
        client.close()


class _CodexRPCClient:
    def __init__(self, env: dict[str, str], timeout: float = 10.0):
        self.timeout = timeout
        self.process = subprocess.Popen(
            [_resolve_codex_executable(env), *CODEX_RPC_ARGS],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self._next_id = 1

    def initialize(self) -> None:
        self.request(
            "initialize",
            {"clientInfo": {"name": "claude-codex-bar", "version": "1.1.0"}},
        )
        self.notify("initialized")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

        while True:
            message = self._read_message()
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                if isinstance(error, dict):
                    message_text = error.get("message") or "unknown app-server error"
                else:
                    message_text = str(error)
                raise CodexRPCError(f"Codex app-server error: {message_text}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise CodexRPCError("Codex app-server returned malformed JSON-RPC.")
            return result

    def _send(self, payload: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise CodexRPCError("Codex app-server stdin is unavailable.")
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()

    def _read_message(self) -> dict[str, Any]:
        if self.process.stdout is None:
            raise CodexRPCError("Codex app-server stdout is unavailable.")

        while True:
            ready, _, _ = select.select([self.process.stdout], [], [], self.timeout)
            if not ready:
                raise CodexRPCError("Codex app-server timed out.")

            line = self.process.stdout.readline()
            if line == "":
                stderr_tail = ""
                if self.process.stderr is not None:
                    try:
                        stderr_tail = self.process.stderr.read().strip()
                    except Exception:
                        stderr_tail = ""
                if stderr_tail:
                    raise CodexRPCError(f"Codex app-server exited: {stderr_tail}")
                raise CodexRPCError("Codex app-server closed its output stream.")

            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(message, dict):
                return message

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=1)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass


def _coalesce_token(tokens: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = tokens.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_iso_datetime(raw: Any) -> dt.datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _resolve_chatgpt_base_url(env: dict[str, str], config_contents: str | None) -> str:
    if config_contents is None:
        config_path = auth_file_path(env).with_name("config.toml")
        try:
            config_contents = config_path.read_text()
        except FileNotFoundError:
            config_contents = None
    if config_contents:
        parsed = _parse_chatgpt_base_url(config_contents)
        if parsed:
            return parsed
    return DEFAULT_USAGE_BASE_URL


def _parse_chatgpt_base_url(contents: str) -> str | None:
    for raw_line in contents.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key != "chatgpt_base_url":
            continue
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        return value.strip() or None
    return None


def _normalize_chatgpt_base_url(base_url: str) -> str:
    normalized = base_url.strip() or DEFAULT_USAGE_BASE_URL
    while normalized.endswith("/"):
        normalized = normalized[:-1]
    if (
        normalized.startswith("https://chatgpt.com")
        or normalized.startswith("https://chat.openai.com")
    ) and "/backend-api" not in normalized:
        normalized += "/backend-api"
    return normalized


def _window_from_usage_payload(raw: Any) -> UsageWindowSnapshot | None:
    if not isinstance(raw, dict):
        return None
    percent = _as_float(raw.get("used_percent"))
    window_seconds = _as_int(raw.get("limit_window_seconds"))
    reset_at = _epoch_to_datetime(raw.get("reset_at"))
    return UsageWindowSnapshot(
        percent=percent,
        resets_at=reset_at,
        window_seconds=window_seconds,
    )


def _window_from_rpc_payload(raw: Any) -> UsageWindowSnapshot | None:
    if not isinstance(raw, dict):
        return None
    percent = _as_float(raw.get("usedPercent"))
    window_mins = _as_int(raw.get("windowDurationMins"))
    return UsageWindowSnapshot(
        percent=percent,
        resets_at=_epoch_to_datetime(raw.get("resetsAt")),
        window_seconds=window_mins * 60 if window_mins is not None else None,
    )


def _select_rpc_rate_limits(payload: dict[str, Any]) -> dict[str, Any] | None:
    limits_by_id = payload.get("rateLimitsByLimitId")
    if isinstance(limits_by_id, dict):
        codex_limits = limits_by_id.get("codex")
        if isinstance(codex_limits, dict):
            return codex_limits

    legacy_limits = payload.get("rateLimits")
    return legacy_limits if isinstance(legacy_limits, dict) else None


def _split_codex_windows(
    windows: list[UsageWindowSnapshot | None],
) -> tuple[UsageWindowSnapshot | None, UsageWindowSnapshot | None]:
    present = [window for window in windows if window and window.percent is not None]
    if not present:
        return None, None

    if len(present) == 1:
        only = present[0]
        if only.window_seconds and only.window_seconds > 8 * 60 * 60:
            return None, only
        return only, None

    known = [window for window in present if window.window_seconds]
    unknown = [window for window in present if not window.window_seconds]
    if len(known) >= 2:
        ordered = sorted(known, key=lambda window: window.window_seconds or 0)
        return ordered[0], ordered[-1]

    if len(known) == 1:
        known_window = known[0]
        other = unknown[0]
        if (known_window.window_seconds or 0) <= 8 * 60 * 60:
            return known_window, other
        return other, known_window

    return present[0], present[-1]


def _resolve_codex_executable(env: dict[str, str]) -> str:
    search_path = env.get("PATH", "")
    override = (env.get(CODEX_CLI_PATH_ENV) or "").strip()
    if override:
        resolved = shutil.which(override, path=search_path)
        if resolved:
            return resolved
        raise CodexRPCError(f"Codex CLI not found at {override}.")

    resolved = shutil.which("codex", path=search_path)
    if resolved:
        return resolved

    home = pathlib.Path(env.get("HOME") or pathlib.Path.home())
    for candidate in (
        pathlib.Path("/opt/homebrew/bin/codex"),
        pathlib.Path("/usr/local/bin/codex"),
        home / ".local" / "bin" / "codex",
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise CodexRPCError(
        f"Codex CLI not found. Set {CODEX_CLI_PATH_ENV} or install Codex in PATH."
    )


def _epoch_to_datetime(raw: Any) -> dt.datetime | None:
    value = _as_int(raw)
    if value is None:
        return None
    return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc)


def _as_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _as_int(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _extract_refresh_error_code(data: bytes) -> str | None:
    try:
        payload = json.loads(data)
    except Exception:
        return None

    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        return code if isinstance(code, str) else None
    if isinstance(error, str):
        return error
    code = payload.get("code")
    return code if isinstance(code, str) else None


def _format_http_error(label: str, status: int, body: str) -> str:
    body = body.strip()
    if body:
        return f"{label} returned HTTP {status}: {body[:160]}"
    return f"{label} returned HTTP {status}."


def _short_error(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__
