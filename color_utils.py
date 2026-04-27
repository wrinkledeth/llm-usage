"""NSAttributedString helpers for claude_bar.py — Claude Code CLI dark theme."""

from enum import Enum

from AppKit import (
    NSMutableAttributedString, NSAttributedString,
    NSColor, NSFont,
    NSForegroundColorAttributeName, NSFontAttributeName,
)


class ColorKey(str, Enum):
    """Named color keys for the menu bar palette."""
    HEADER = "header"
    BAR_EMPTY = "bar_empty"
    PERCENT = "percent"
    RESET_TIME = "reset_time"
    CREDITS = "credits"
    LAST_UPDATED = "last_updated"
    ERROR = "error"
    CODEX_ACCENT = "codex_accent"
    CLAUDE_ACCENT = "claude_accent"


PROGRESS_WIDTH = 16

# ── Palette ──────────────────────────────────────────────────────────────────
_HEX: dict[ColorKey, str] = {
    ColorKey.BAR_EMPTY:     "#3A3A3A",
    ColorKey.ERROR:         "#F44747",
    ColorKey.CODEX_ACCENT:  "#7BA3CD",
    ColorKey.CLAUDE_ACCENT: "#C68870",
}


def _hex_to_nscolor(hex_color: str):
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255
    g = int(hex_color[2:4], 16) / 255
    b = int(hex_color[4:6], 16) / 255
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)


# Keys in this set inherit the menu's default text color and font (matching
# Refresh/Quit) by leaving foreground/font attributes unset. NSColor.labelColor()
# does NOT match: attributed-title rendering bypasses the vibrancy treatment
# plain titles get.
_LABEL_KEYS = frozenset({
    ColorKey.HEADER,
    ColorKey.PERCENT,
    ColorKey.RESET_TIME,
    ColorKey.CREDITS,
    ColorKey.LAST_UPDATED,
})
_COLORS = {key: _hex_to_nscolor(hex_val) for key, hex_val in _HEX.items()}
_FONT_REG = NSFont.menuFontOfSize_(13.0)
_FONT_BOLD = NSFont.boldSystemFontOfSize_(13.0)
_FONT_MONO = NSFont.monospacedSystemFontOfSize_weight_(12.0, 0.0)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _attrs(color_key: ColorKey, bold: bool = False, mono: bool = False) -> dict:
    attrs = {}
    if mono:
        attrs[NSFontAttributeName] = _FONT_MONO
    elif bold:
        attrs[NSFontAttributeName] = _FONT_BOLD
    elif color_key not in _LABEL_KEYS:
        attrs[NSFontAttributeName] = _FONT_REG
    if color_key in _COLORS:
        attrs[NSForegroundColorAttributeName] = _COLORS[color_key]
    return attrs


def _attr_str(text: str, color_key: ColorKey, bold: bool = False, mono: bool = False):
    return NSAttributedString.alloc().initWithString_attributes_(text, _attrs(color_key, bold, mono))


def _progress_line(pct: float, width: int = PROGRESS_WIDTH) -> tuple[str, str]:
    filled = min(round(pct / 100 * width), width)
    return "▰" * filled, "▱" * (width - filled)


def make_plain(text: str, color_key: ColorKey, bold: bool = False, mono: bool = False):
    """Single-color NSAttributedString."""
    return _attr_str(text, color_key, bold=bold, mono=mono)


def set_menu_title(menuitem, attr_string) -> None:
    """Apply attributed string to a rumps.MenuItem. Never assign .title afterwards."""
    menuitem._menuitem.setAttributedTitle_(attr_string)


def make_section_header(label: str, accent_color_key: ColorKey):
    """Bold header preceded by a colored bullet that identifies the provider."""
    result = NSMutableAttributedString.alloc().init()
    result.appendAttributedString_(_attr_str("● ", accent_color_key))
    result.appendAttributedString_(_attr_str(label, ColorKey.HEADER, bold=True))
    return result


def make_progress_row(
    pct: float,
    suffix: str,
    accent_color_key: ColorKey,
    prefix: str = "",
    width: int = PROGRESS_WIDTH,
):
    """Progress row in mono font so prefix/percent/bar/suffix columns align."""
    filled, empty = _progress_line(pct, width)
    result = NSMutableAttributedString.alloc().init()
    head = f"  {prefix:<3} {pct:>3.0f}%  " if prefix else f"  {pct:>3.0f}%  "
    result.appendAttributedString_(_attr_str(head, ColorKey.PERCENT, mono=True))
    result.appendAttributedString_(_attr_str(filled, accent_color_key, mono=True))
    result.appendAttributedString_(_attr_str(empty, ColorKey.BAR_EMPTY, mono=True))
    result.appendAttributedString_(_attr_str(suffix, ColorKey.RESET_TIME, mono=True))
    return result
