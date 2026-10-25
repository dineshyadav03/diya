"""The shell and the sky (frontend/components/AppShell.jsx, frontend/app/globals.css; docs/UI_DESIGN.md), restyled on 2026-10-26 at the owner's request after the look of Hark's interface.

What this proves, from the source (the painted page is the design rig's job and was checked in both themes at three widths on 2026-10-26): the three pages in the pill are Today, Chat and Memory and every page
of the app is in the menu, so nothing became unreachable when the sidebar went; the menu is a real disclosure (a button that says whether it is open and which list it controls, closed by Escape, by a tap
outside and by going to another page) and holds the theme choice and the sign-out; the slider under the pill is decoration and the current page is said by aria-current, not by colour; the sky is drawn by the
stylesheet alone and is never lighter than --bg in the dark theme (never darker in the light one), which is what makes the contrast figures in tests/test_frontend_theme.py true of the real page; the two dark
copies of the tokens are identical, glass tokens included; and the pill fits a 320 px screen.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHELL = (ROOT / "frontend" / "components" / "AppShell.jsx").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")


def block(opening):
    start = CSS.index(opening) + len(opening)
    depth, end = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(CSS[end], 0)
        end += 1
    return CSS[start:end - 1]


def luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


LIGHT = block(":root {")
DARK_SYSTEM = block(':root:not([data-theme="light"]) {')
DARK_CHOICE = block(':root[data-theme="dark"] {')


def listed(name):
    body = SHELL.split(f"export const {name} = [", 1)[1].split("\n]\n", 1)[0]
    return re.findall(r"href: '([^']+)', name: '([^']+)'", body)


def test_the_pill_holds_today_chat_and_memory_and_every_page_is_in_the_menu():
    assert listed("TABS") == [("/today", "Today"), ("/", "Chat"), ("/memory", "Memory")]
    menu = {href for href, _name in listed("NAV")}
    pages = {"/" + path.parent.name for path in (ROOT / "frontend" / "app").glob("*/page.js")} | {"/"}
    pages.discard("/login")  # the sign-in page is drawn without the shell
    assert menu == pages, (sorted(menu ^ pages))
    assert {href for href, _name in listed("TABS")} <= menu


def test_the_menu_is_a_real_disclosure_closed_by_escape_a_tap_outside_and_a_new_page():
    assert 'aria-expanded={open}' in SHELL and 'aria-controls="site-nav"' in SHELL and 'id="site-nav"' in SHELL
    assert "event.key === 'Escape'" in SHELL and "setOpen(false)" in SHELL and 'className="menu-scrim"' in SHELL and "useEffect(() => setOpen(false), [pathname])" in SHELL
    sheet = SHELL.split('<nav className="menu-sheet"', 1)[1]
    assert "<ThemeToggle />" in sheet and "<SignOut />" in sheet  # the theme choice and the sign-out live in the menu
    assert 'aria-label="All pages"' in SHELL and 'aria-label="Main pages"' in SHELL  # two navigations, each named


def test_the_slider_is_decoration_and_the_current_page_is_said_in_words_for_a_screen_reader():
    assert 'className="hub-slider" aria-hidden="true"' in SHELL
    assert SHELL.count("aria-current={isCurrent(item.href) ? 'page' : undefined}") == 2  # the pill and the menu
    assert '[aria-current="page"]' in CSS and ".hub-slider" in CSS and "translateX(calc(var(--tab, 0) * 100%))" in CSS
    assert "tab >= 0 ? tab : undefined" in SHELL  # on a page that is not one of the three the slider is hidden, not left under the wrong one


def test_the_menu_is_closed_until_opened_and_the_pill_fits_a_320_pixel_screen():
    assert re.search(r"\.menu-sheet \{[^}]*display: none", CSS) and re.search(r'\.shell\[data-nav-open="true"\] \.menu-sheet \{ display: block; \}', CSS)
    narrow = CSS.split("@media (max-width: 400px) {", 1)[1].split("\n}\n", 1)[0]
    assert ".hub-pill" in narrow and "minmax(58px, 1fr)" in narrow and ".hub-tab" in narrow
    # 3 tabs of at least 58 px + the pill's padding and two 44 px buttons and the gaps and sides fit in 320
    assert 3 * 58 + 6 + 2 * 44 + 2 * 6 + 2 * 12 <= 320


def test_the_sky_is_drawn_by_the_stylesheet_alone_and_never_lighter_than_bg_in_the_dark_theme_or_darker_in_the_light_one():
    assert re.search(r"body::before \{[^}]*background: var\(--sky\)", CSS) and "z-index: -1" in CSS
    for name, text, lighter_ok in (("dark (system)", DARK_SYSTEM, False), ("dark (choice)", DARK_CHOICE, False), ("light", LIGHT, True)):
        bg = re.search(r"--bg: (#[0-9a-fA-F]{6})", text).group(1)
        sky = text.split("--sky:", 1)[1].split(";", 1)[0]
        stops = re.findall(r"#[0-9a-fA-F]{6}", sky)
        assert stops, name
        for stop in stops:
            if lighter_ok:
                assert luminance(stop) >= luminance(bg) - 1e-9, (name, stop, bg)  # the light sky is never darker than the figure the contrast tests used
            else:
                assert luminance(stop) <= luminance(bg) + 1e-9, (name, stop, bg)  # the dark sky is never lighter than it
        for alpha in re.findall(r"rgba\([^)]*,\s*([0-9.]+)\)", sky):
            assert float(alpha) <= (0.75 if lighter_ok else 0.25), (name, alpha)  # a highlight on the dark sky is too faint to lift it past --bg


def test_the_two_dark_copies_are_identical_glass_and_sky_included():
    normal = lambda text: re.sub(r"\s+", " ", text).strip()
    assert normal(DARK_SYSTEM) == normal(DARK_CHOICE)
    for token in ("--glass:", "--glass-strong:", "--glass-user:", "--glass-hover:", "--glass-edge:", "--sky:", "--avatar:"):
        assert token in LIGHT and token in DARK_SYSTEM and token in DARK_CHOICE, token


def test_the_page_titles_are_the_lowercase_serif_of_the_reference():
    assert "--serif:" in LIGHT and re.search(r"h1 \{ font-family: var\(--serif\); font-weight: 500; text-transform: lowercase; \}", CSS)
