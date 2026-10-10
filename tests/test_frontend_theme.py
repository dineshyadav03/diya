"""The two themes (docs/UI_DESIGN.md, D1 and D6): frontend/app/globals.css.

What this proves: the dark theme is written twice (once for the operating system's setting, once for an explicit choice) and the
two copies are the same; every colour pairing the interface relies on clears the contrast it is used at, in both themes, computed
with the WCAG 2.x formula from the stylesheet's own values (text at 4.5:1, the edge of a field or a button at 3:1); the theme is
applied before the page paints and only ever to the two names the sidebar writes; and nothing in the stylesheet reaches another host.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSS = (ROOT / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
LAYOUT = (ROOT / "frontend" / "app" / "layout.js").read_text(encoding="utf-8")
SHELL = (ROOT / "frontend" / "components" / "AppShell.jsx").read_text(encoding="utf-8")


def block(opening):
    """The text between the braces of the rule that starts at `opening`."""
    start = CSS.index(opening) + len(opening)
    depth, end = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(CSS[end], 0)
        end += 1
    return CSS[start:end - 1]


def tokens(text):
    return dict(re.findall(r"(--[a-z-]+):\s*(#[0-9a-fA-F]{6})\b", text))


LIGHT = tokens(block(":root {"))
DARK_BY_SYSTEM = tokens(block(':root:not([data-theme="light"]) {'))
DARK_BY_CHOICE = tokens(block(':root[data-theme="dark"] {'))
DARK = {**LIGHT, **DARK_BY_CHOICE}  # a dark token that is not repeated keeps its light value


def luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# (foreground token, background token, the least ratio it is used at, what it is)
PAIRS = [
    ("--text", "--bg", 4.5, "body text on the page"),
    ("--text", "--surface", 4.5, "text on a card, a field and the composer"),
    ("--text", "--surface-hover", 4.5, "the person's own messages, and a hovered row"),
    ("--text-dim", "--bg", 4.5, "secondary text on the page and the sidebar"),
    ("--text-dim", "--surface", 4.5, "secondary text and placeholders on a card"),
    ("--text-dim", "--surface-hover", 4.5, "secondary text on a hovered row"),
    ("--accent-text", "--accent", 4.5, "the label of the primary action"),
    ("--link", "--bg", 4.5, "links on the page"),
    ("--link", "--surface", 4.5, "links on a card"),
    ("--danger-text", "--bg", 4.5, "an error on the page"),
    ("--danger-text", "--surface", 4.5, "an error on a card"),
    ("--danger-fill-text", "--danger", 4.5, "the label on a recording button, the mark on a failed send"),
    ("--border-strong", "--bg", 3.0, "the edge of a button on the page"),
    ("--border-strong", "--surface", 3.0, "the edge of a field and of the composer"),
    ("--accent", "--bg", 3.0, "the primary action against the page"),
]


def test_the_dark_theme_is_written_twice_and_both_copies_are_the_same():
    assert DARK_BY_SYSTEM and DARK_BY_SYSTEM == DARK_BY_CHOICE
    assert set(DARK_BY_CHOICE) <= set(LIGHT)  # every token the dark theme sets, the light one sets too


def test_the_two_themes_are_the_two_systems_they_say_they_are():
    assert (LIGHT["--bg"], LIGHT["--surface"], LIGHT["--accent"]) == ("#f6f5f4", "#ffffff", "#0075de")  # Notion: warm paper, white cards, one blue
    assert (DARK["--bg"], DARK["--surface"], DARK["--accent"]) == ("#0a0a0a", "#191919", "#ffffff")  # xAI: near-black, charcoal, the white pill


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("foreground, background, least, what", PAIRS)
def test_every_pairing_clears_the_contrast_it_is_used_at(theme, foreground, background, least, what):
    palette = LIGHT if theme == "light" else DARK
    ratio = contrast(palette[foreground], palette[background])
    assert ratio >= least, f"{theme}: {what} ({foreground} on {background}) is {ratio:.2f}:1, needs {least}:1"


def test_the_hairline_is_only_decoration_and_a_field_never_relies_on_it():
    """--border is far below 3:1 on purpose (it is the line round a card); a field, a button and the composer use --border-strong."""
    fields = [rule for rule in re.findall(r"\.(?:memory-input|composer|composer-btn|memory-btn|quiet-btn|menu-btn|theme-toggle)\s*\{([^}]*)\}", CSS)]
    assert fields and all("var(--border)" not in rule for rule in fields)
    assert contrast(LIGHT["--border"], LIGHT["--bg"]) < 3 and contrast(DARK["--border"], DARK["--bg"]) < 3


def test_the_theme_is_applied_before_the_page_paints_and_only_to_the_two_names_the_sidebar_writes():
    assert "THEME_BEFORE_PAINT" in LAYOUT and "dangerouslySetInnerHTML={{ __html: THEME_BEFORE_PAINT }}" in LAYOUT
    assert "if(t==='light'||t==='dark')document.documentElement.dataset.theme=t" in LAYOUT  # nothing else from storage is written to the page
    assert "suppressHydrationWarning" in LAYOUT
    assert re.findall(r"value: '([a-z]+)'", SHELL) == ["system", "light", "dark"]
    assert "localStorage.removeItem('diya_theme')" in SHELL and "localStorage.setItem('diya_theme', value)" in SHELL
    assert "themeColor" in LAYOUT and "prefers-color-scheme: light" in LAYOUT and "prefers-color-scheme: dark" in LAYOUT


def test_the_stylesheet_asks_nobody_for_anything():
    assert not re.search(r"https?://|@import|url\((?!['\"]?/icons/)", CSS)  # only the two local icons are referenced


def test_motion_is_switched_off_when_the_system_asks_for_less():
    assert "@media (prefers-reduced-motion: reduce)" in CSS and "animation-duration: 0.01ms !important" in CSS


def test_every_touch_target_is_44_pixels_on_a_phone():
    coarse = " ".join(re.findall(r"@media \(pointer: coarse\) \{(.*?)\}\s*(?=\n|/\*|\.|@)", CSS, flags=re.S))
    for name in ("quiet-btn", "composer-btn", "memory-btn"):
        assert name in coarse, name
    assert "min-height: 44px" in CSS and "height: 44px" in CSS
