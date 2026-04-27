#!/usr/bin/env python3
"""Claude + Codex usage macOS menu bar app."""

import argparse
import datetime
import json
import pathlib
import subprocess
import threading
import urllib.request
from datetime import timezone

import rookiepy
import rumps
from AppKit import NSImage
from curl_cffi import requests
from PyObjCTools.AppHelper import callAfter

from codex_usage import load_codex_snapshot
from color_utils import (
    ColorKey,
    make_plain,
    make_progress_row,
    make_section_header,
    set_menu_title,
)
from repo_metadata import github_releases_url, resolve_github_repo
from status_image import StatusBarContentView, provider_specs, status_item_size
from usage_models import CreditsSnapshot, ProviderUsageSnapshot, UsageWindowSnapshot

VERSION = "1.1.0"
REPO_ROOT = pathlib.Path(__file__).parent

REFRESH_INTERVAL = 300
STATUS_SETUP_DELAY_SECS = 0.5
UPDATE_CHECK_DELAY_SECS = 5.0
COOKIE_NAMES = ("sessionKey", "__Secure-next-auth.session-token")
BROWSERS = ("chrome", "safari", "firefox", "brave", "edge")

# Set to False to show only the provider icons in the menu bar.
SHOW_TITLE_SUMMARY = True


def _parse_version(tag: str) -> tuple[int, ...]:
    return tuple(int(x) for x in tag.lstrip("v").split("."))


def check_for_update(github_repo: str) -> tuple[str, str] | None:
    """Return (tag_name, html_url) if a newer release exists on GitHub, else None."""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{github_repo}/releases/latest",
            headers={"User-Agent": "claude-codex-bar"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        tag = data.get("tag_name", "")
        html_url = data.get("html_url", "")
        if tag and _parse_version(tag) > _parse_version(VERSION):
            return tag, html_url
    except Exception as exc:
        print(f"[claude_bar] update check error: {type(exc).__name__}: {exc}")
    return None


def get_session_cookie(browser: str):
    """Return (name, value) for the first matching claude.ai session cookie."""
    try:
        loader = getattr(rookiepy, browser)
        for cookie in loader(["claude.ai"]):
            if cookie["name"] in COOKIE_NAMES:
                return cookie["name"], cookie["value"]
    except Exception as exc:
        print(f"[claude_bar] {browser}: {type(exc).__name__}")
    return None, None


def build_session(browser: str | None = None) -> requests.Session:
    """Build a requests.Session with the claude.ai session cookie attached."""
    browsers_to_try = (browser,) if browser else BROWSERS
    for candidate in browsers_to_try:
        name, value = get_session_cookie(candidate)
        if value:
            print(f"[claude_bar] Using cookie '{name}' from {candidate}")
            session = requests.Session(impersonate="chrome120")
            session.cookies.set(name, value, domain="claude.ai")
            return session
    if browser:
        raise RuntimeError(f"No session cookie found in '{browser}'.")
    raise RuntimeError(
        "No claude.ai session cookie found. Log in to Claude in Chrome, Safari, Firefox, Brave, or Edge first."
    )


def get_org_id(session: requests.Session) -> str:
    resp = session.get("https://claude.ai/api/organizations", timeout=10)
    resp.raise_for_status()
    orgs = resp.json()
    if not orgs:
        raise RuntimeError("No organizations returned from API")
    org = orgs[0]
    org_id = org.get("uuid") or org.get("id")
    if not org_id:
        raise RuntimeError("Organization has no 'uuid' or 'id' field")
    return org_id


def fetch_usage(session: requests.Session, org_id: str) -> dict:
    resp = session.get(
        f"https://claude.ai/api/organizations/{org_id}/usage",
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _coerce_datetime(value) -> datetime.datetime | None:
    if isinstance(value, datetime.datetime):
        return value
    if not isinstance(value, str):
        return None
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def fmt_reset(value) -> str:
    """Format time remaining until reset as '2h 23m' or '1d 7h' for longer periods."""
    dt = _coerce_datetime(value)
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    total_secs = max(0, int((dt - datetime.datetime.now(timezone.utc)).total_seconds()))
    days, rem = divmod(total_secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days > 0:
        return f"{days}d {hours}h"
    return f"{hours}h {minutes:02d}m"


def _as_float(value, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_error(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        if response.status_code == 401:
            return "session expired"
        return f"HTTP {response.status_code}"
    message = str(exc).strip()
    if not message:
        return type(exc).__name__
    return message[:140]


def build_claude_snapshot(data: dict) -> ProviderUsageSnapshot:
    five_hour = data.get("five_hour")
    seven_day = data.get("seven_day")
    if not isinstance(five_hour, dict) or not isinstance(seven_day, dict):
        raise RuntimeError("Unexpected Claude usage response shape.")

    credits_payload = data.get("extra_usage") or {}
    credits = None
    if isinstance(credits_payload, dict) and credits_payload.get("is_enabled"):
        credits = CreditsSnapshot(
            kind="claude_extra",
            enabled=True,
            used=(_as_float(credits_payload.get("used_credits"), 0.0) or 0.0) / 100,
            limit=(_as_float(credits_payload.get("monthly_limit"), 0.0) or 0.0) / 100,
            utilization=_as_float(credits_payload.get("utilization"), 0.0),
        )

    return ProviderUsageSnapshot(
        provider_id="claude",
        display_name="Claude",
        session=UsageWindowSnapshot(
            percent=_as_float(five_hour.get("utilization"), 0.0),
            resets_at=_coerce_datetime(five_hour.get("resets_at")),
            window_seconds=5 * 60 * 60,
        ),
        weekly=UsageWindowSnapshot(
            percent=_as_float(seven_day.get("utilization"), 0.0),
            resets_at=_coerce_datetime(seven_day.get("resets_at")),
            window_seconds=7 * 24 * 60 * 60,
        ),
        credits=credits,
        last_updated=datetime.datetime.now(datetime.timezone.utc),
    )


class ClaudeBar(rumps.App):
    def __init__(self, browser: str | None = None):
        super().__init__("Claude + Codex", "…")
        self._browser = browser
        self._github_repo = resolve_github_repo(REPO_ROOT)
        self._build_menu_items()
        self._init_state()
        self._apply_section_headers()
        self.update_item.hidden = True
        self._refresh(None)
        rumps.Timer(self._setup_status_item, STATUS_SETUP_DELAY_SECS).start()
        rumps.Timer(self._start_update_check, UPDATE_CHECK_DELAY_SECS).start()

    def _build_menu_items(self):
        self.codex_hdr = self._display_item("◆ Codex")
        self.codex_session_row = self._display_item("  …")
        self.codex_weekly_row = self._display_item("  …")
        self.codex_detail_row = self._display_item("  …")

        self.claude_hdr = self._display_item("◆ Claude")
        self.claude_session_row = self._display_item("  …")
        self.claude_weekly_row = self._display_item("  …")
        self.claude_detail_row = self._display_item("  …")

        self.refresh_btn = rumps.MenuItem("Refresh", callback=self.on_refresh)
        self.update_item = rumps.MenuItem("  Update available", callback=self.on_open_update)

        self.menu = [
            self.refresh_btn,
            None,
            self.codex_hdr,
            self.codex_session_row,
            self.codex_weekly_row,
            self.codex_detail_row,
            None,
            self.claude_hdr,
            self.claude_session_row,
            self.claude_weekly_row,
            self.claude_detail_row,
            None,
            self.update_item,
        ]

    def _display_item(self, title: str) -> rumps.MenuItem:
        return rumps.MenuItem(title, callback=self._noop_display_item)

    def _noop_display_item(self, _):
        pass

    def _init_state(self):
        self._session: requests.Session | None = None
        self._org_id: str | None = None
        self._refreshing = False
        self._refresh_lock = threading.Lock()
        self._show_summary = SHOW_TITLE_SUMMARY
        self._status_item_ready = False
        self._codex_snapshot: ProviderUsageSnapshot | None = None
        self._claude_snapshot: ProviderUsageSnapshot | None = None
        self._update_url = github_releases_url(self._github_repo)
        self.codex_detail_row.hidden = True
        self.claude_detail_row.hidden = True

    def _apply_section_headers(self):
        set_menu_title(self.codex_hdr, make_section_header("Codex", ColorKey.CODEX_ACCENT))
        set_menu_title(self.claude_hdr, make_section_header("Claude", ColorKey.CLAUDE_ACCENT))

    def _setup_status_item(self, timer):
        timer.stop()
        self._status_item_ready = True
        self._ensure_status_view()
        self._refresh_status_item()

    def _refresh_status_item(self):
        if not self._status_item_ready or not hasattr(self, "_nsapp"):
            return

        status_item = self._nsapp.nsstatusitem
        button = status_item.button()
        if button is None:
            return

        self._ensure_status_view()
        width, height = status_item_size(self._show_summary)
        button_height = button.bounds().size.height
        self._status_view.apply_state(
            provider_specs(self._codex_snapshot, self._claude_snapshot),
            self._show_summary,
        )
        status_view_y = max(0.0, (button_height - height) / 2)
        self._status_view.setFrame_(((0.0, status_view_y), (width, height)))
        status_item.setLength_(width)
        self.title = None
        button.setNeedsDisplay_(True)

    def _ensure_status_view(self):
        if getattr(self, "_status_view", None) is not None or not hasattr(self, "_nsapp"):
            return

        status_item = self._nsapp.nsstatusitem
        button = status_item.button()
        if button is None:
            return

        width, height = status_item_size(self._show_summary)
        self._status_view = StatusBarContentView.alloc().initWithFrame_(((0.0, 0.0), (width, height)))
        button.addSubview_(self._status_view)
        status_item.setImage_(NSImage.alloc().init())
        status_item.setTitle_("")

    def on_refresh(self, _):
        self._refresh(None)

    def on_open_update(self, _):
        subprocess.Popen(["open", self._update_url])

    @rumps.timer(REFRESH_INTERVAL)
    def _auto_refresh(self, _):
        self._refresh(None)

    def _start_update_check(self, timer):
        timer.stop()
        threading.Thread(target=self._check_update_bg, daemon=True).start()

    def _check_update_bg(self):
        result = check_for_update(self._github_repo)
        if result:
            tag, url = result
            self._update_url = url
            callAfter(self._show_update_banner, tag)

    def _show_update_banner(self, tag: str):
        self.update_item.title = f"  Update available: {tag} - click to open"
        self.update_item.hidden = False

    def _ensure_claude_session(self):
        if self._session is None:
            self._session = build_session(self._browser)
        if self._org_id is None:
            self._org_id = get_org_id(self._session)

    def _refresh(self, _):
        with self._refresh_lock:
            if self._refreshing:
                return
            self._refreshing = True
        threading.Thread(target=self._refresh_bg, daemon=True).start()

    def _refresh_bg(self):
        try:
            claude_snapshot = self._load_claude_snapshot()
            codex_snapshot = self._load_codex_snapshot()
            callAfter(self._apply_refresh_results, claude_snapshot, codex_snapshot)
        finally:
            with self._refresh_lock:
                self._refreshing = False

    def _load_claude_snapshot(self) -> ProviderUsageSnapshot:
        try:
            self._ensure_claude_session()
            data = fetch_usage(self._session, self._org_id)
            return build_claude_snapshot(data)
        except Exception as exc:
            response = getattr(exc, "response", None)
            if response is not None and response.status_code == 401:
                self._session = None
                self._org_id = None
            return ProviderUsageSnapshot.error_state("claude", "Claude", _format_error(exc))

    def _load_codex_snapshot(self) -> ProviderUsageSnapshot:
        try:
            return load_codex_snapshot()
        except Exception as exc:
            return ProviderUsageSnapshot.error_state("codex", "Codex", _format_error(exc))

    def _apply_refresh_results(
        self,
        claude_snapshot: ProviderUsageSnapshot,
        codex_snapshot: ProviderUsageSnapshot,
    ):
        self._claude_snapshot = claude_snapshot
        self._codex_snapshot = codex_snapshot
        self._render_provider_snapshot(
            snapshot=codex_snapshot,
            session_row=self.codex_session_row,
            weekly_row=self.codex_weekly_row,
            detail_row=self.codex_detail_row,
            accent_color_key=ColorKey.CODEX_ACCENT,
        )
        self._render_provider_snapshot(
            snapshot=claude_snapshot,
            session_row=self.claude_session_row,
            weekly_row=self.claude_weekly_row,
            detail_row=self.claude_detail_row,
            accent_color_key=ColorKey.CLAUDE_ACCENT,
        )
        self._refresh_status_item()

    def _render_provider_snapshot(
        self,
        snapshot: ProviderUsageSnapshot,
        session_row: rumps.MenuItem,
        weekly_row: rumps.MenuItem,
        detail_row: rumps.MenuItem,
        accent_color_key: ColorKey,
    ):
        self._render_window_row(
            session_row,
            snapshot.session,
            label="5h",
            is_weekly=False,
            failed=bool(snapshot.error),
            accent_color_key=accent_color_key,
        )
        self._render_window_row(
            weekly_row,
            snapshot.weekly,
            label="7d",
            is_weekly=True,
            failed=bool(snapshot.error),
            accent_color_key=accent_color_key,
        )

        if snapshot.error:
            set_menu_title(detail_row, make_plain(f"  Error: {snapshot.error}", ColorKey.ERROR))
            detail_row.hidden = False
            return

        credits = snapshot.credits
        if credits and credits.enabled:
            set_menu_title(detail_row, make_plain(self._credits_text(credits), ColorKey.CREDITS))
            detail_row.hidden = False
            return

        detail_row.hidden = True

    def _render_window_row(
        self,
        row_item: rumps.MenuItem,
        window: UsageWindowSnapshot | None,
        label: str,
        is_weekly: bool,
        failed: bool,
        accent_color_key: ColorKey,
    ):
        if window and window.percent is not None:
            suffix = self._window_suffix(window, is_weekly)
            set_menu_title(
                row_item,
                make_progress_row(window.percent, suffix, accent_color_key, prefix=label),
            )
            return

        color = ColorKey.ERROR if failed else ColorKey.LAST_UPDATED
        set_menu_title(row_item, make_plain(f"  {label} unavailable", color))

    def _window_suffix(self, window: UsageWindowSnapshot, is_weekly: bool) -> str:
        reset_text = fmt_reset(window.resets_at)
        if reset_text == "unknown":
            reset_text = "unknown" if is_weekly else "idle"
        return f"  {reset_text:>7}"

    def _credits_text(self, credits: CreditsSnapshot) -> str:
        if credits.kind == "codex_balance":
            if credits.unlimited:
                return "  Credits: unlimited"
            if credits.balance is not None:
                return f"  Credits: ${credits.balance:,.2f}"
            return "  Credits available"

        used = credits.used or 0.0
        limit = credits.limit or 0.0
        utilization = credits.utilization or 0.0
        return f"  Extra usage: ${used:.2f} of ${limit:,.0f} ({utilization:.2f}%)"


def main():
    parser = argparse.ArgumentParser(description="Claude + Codex usage menu bar app")
    parser.add_argument(
        "--browser",
        choices=list(BROWSERS),
        metavar="BROWSER",
        help=f"Browser to read Claude session cookie from. Choices: {', '.join(BROWSERS)}",
    )
    args = parser.parse_args()
    ClaudeBar(browser=args.browser).run()


if __name__ == "__main__":
    main()
