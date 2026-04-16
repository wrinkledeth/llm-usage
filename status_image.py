from __future__ import annotations

import pathlib

import objc
from AppKit import (
    NSAttributedString,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSImageScaleProportionallyUpOrDown,
    NSImageView,
    NSStatusBar,
    NSView,
)

from usage_models import ProviderUsageSnapshot

CLAUDE_ICON_PATH = pathlib.Path(__file__).parent / "icons8-claude-ai-96.png"
CODEX_ICON_PATH = pathlib.Path(__file__).parent / "openai-codex-icon.svg"
# Match the actual menu bar thickness so the stacked text can be centered
# within the full control instead of getting clipped against a shorter view.
STATUS_HEIGHT = NSStatusBar.systemStatusBar().thickness()
ICON_BOX_WIDTH = 14.75
ICON_DRAW_SIZE = 14.25
ICON_TOP_OFFSET = 2.75
TEXT_GAP = 1.5
PROVIDER_GAP = 6.0
SIDE_PADDING = 2.0
TOP_TEXT_Y = 9.25
BOTTOM_TEXT_Y = -0.5
VALUE_FONT = NSFont.monospacedDigitSystemFontOfSize_weight_(10.0, 0.3)
_CLAUDE_ICON: NSImage | None = None
_CODEX_ICON: NSImage | None = None


def status_item_size(show_summary: bool) -> tuple[float, float]:
    provider_width = _provider_width(show_summary)
    width = SIDE_PADDING * 2 + provider_width * 2 + PROVIDER_GAP
    return width, STATUS_HEIGHT


def provider_specs(
    codex_snapshot: ProviderUsageSnapshot | None,
    claude_snapshot: ProviderUsageSnapshot | None,
) -> list[dict[str, object]]:
    return [
        _provider_spec(codex_snapshot, "codex"),
        _provider_spec(claude_snapshot, "claude"),
    ]


class PassthroughView(NSView):
    def hitTest_(self, point):
        return None


class StatusBarContentView(PassthroughView):
    def initWithFrame_(self, frame):
        self = objc.super(StatusBarContentView, self).initWithFrame_(frame)
        if self is None:
            return None

        self._providers: list[dict[str, object]] = []
        self._show_summary = True
        self._icon_views: dict[str, NSImageView] = {}

        for provider_id, icon in (("codex", _codex_icon()), ("claude", _claude_icon())):
            icon_view = NSImageView.alloc().initWithFrame_(((0.0, 0.0), (ICON_DRAW_SIZE, ICON_DRAW_SIZE)))
            icon_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
            if icon is not None:
                icon_view.setImage_(icon)
            self.addSubview_(icon_view)
            self._icon_views[provider_id] = icon_view

        return self

    @objc.python_method
    def apply_state(self, providers: list[dict[str, object]], show_summary: bool) -> None:
        self._providers = providers
        self._show_summary = show_summary

        provider_width = _provider_width(show_summary)
        x = SIDE_PADDING
        for spec in providers:
            provider_id = str(spec["provider_id"])
            icon_view = self._icon_views[provider_id]
            icon_view.setFrame_(((x, ICON_TOP_OFFSET), (ICON_DRAW_SIZE, ICON_DRAW_SIZE)))
            icon_view.setContentTintColor_(_render_color(bool(spec["dimmed"])))
            x += provider_width + PROVIDER_GAP

        width, height = status_item_size(show_summary)
        self.setFrameSize_((width, height))
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        if not self._show_summary:
            return

        provider_width = _provider_width(self._show_summary)
        x = SIDE_PADDING
        for spec in self._providers:
            dimmed = bool(spec["dimmed"])
            text_x = x + ICON_BOX_WIDTH + TEXT_GAP
            _attributed_text(str(spec["session_text"]), dimmed).drawAtPoint_((text_x, TOP_TEXT_Y))
            _attributed_text(str(spec["weekly_text"]), dimmed).drawAtPoint_((text_x, BOTTOM_TEXT_Y))
            x += provider_width + PROVIDER_GAP


def _provider_spec(snapshot: ProviderUsageSnapshot | None, provider_id: str) -> dict[str, object]:
    snapshot = snapshot or ProviderUsageSnapshot.error_state(provider_id, provider_id.title(), "Loading...")
    session_text = _percent_text(snapshot.session.percent if snapshot.session else None)
    weekly_text = _percent_text(snapshot.weekly.percent if snapshot.weekly else None)
    dimmed = bool(snapshot.error) or not snapshot.has_any_usage
    return {
        "provider_id": provider_id,
        "session_text": session_text,
        "weekly_text": weekly_text,
        "dimmed": dimmed,
    }


def _provider_width(show_summary: bool) -> float:
    if not show_summary:
        return ICON_BOX_WIDTH + 1.0
    sample = _attributed_text("100%", False)
    return ICON_BOX_WIDTH + TEXT_GAP + sample.size().width


def _render_color(dimmed: bool) -> NSColor:
    base = NSColor.textColor()
    if dimmed:
        return base.colorWithAlphaComponent_(0.55)
    return base


def _claude_icon() -> NSImage | None:
    global _CLAUDE_ICON
    if _CLAUDE_ICON is not None:
        return _CLAUDE_ICON
    if not CLAUDE_ICON_PATH.exists():
        return None
    icon = NSImage.alloc().initByReferencingFile_(str(CLAUDE_ICON_PATH))
    if icon is None:
        return None
    icon.setTemplate_(True)
    _CLAUDE_ICON = icon
    return _CLAUDE_ICON


def _codex_icon() -> NSImage | None:
    global _CODEX_ICON
    if _CODEX_ICON is not None:
        return _CODEX_ICON
    if not CODEX_ICON_PATH.exists():
        return None
    icon = NSImage.alloc().initByReferencingFile_(str(CODEX_ICON_PATH))
    if icon is None:
        return None
    icon.setTemplate_(True)
    _CODEX_ICON = icon
    return _CODEX_ICON


def _attributed_text(text: str, dimmed: bool) -> NSAttributedString:
    attrs = {
        NSFontAttributeName: VALUE_FONT,
        NSForegroundColorAttributeName: _render_color(dimmed),
    }
    return NSAttributedString.alloc().initWithString_attributes_(text, attrs)


def _percent_text(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{round(value):.0f}%"
