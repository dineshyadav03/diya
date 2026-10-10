"""How the login (frontend/server/ui-login.mjs, tested in test_ui_login.py) is wired into the UI, checked from the source, as the pages'
failure handling is (test_frontend_failure_messages.py): the middleware hands every request to the guard and covers everything but static
files; /session is served by the same module; the sign-in page and the sidebar use /session and nothing else; the cookie is never
visible to the browser's scripts; the shell is not drawn round the sign-in page. In a real browser it is checked by using the UI.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
MIDDLEWARE = FRONTEND / "middleware.js"
SESSION = FRONTEND / "app" / "session" / "route.js"
LOGIN = FRONTEND / "app" / "login" / "page.js"
SHELL = FRONTEND / "components" / "AppShell.jsx"
CSS = FRONTEND / "app" / "globals.css"


def read(path):
    return path.read_text(encoding="utf-8")


def matcher():
    found = re.search(r"matcher:\s*\['([^']+)'\]", read(MIDDLEWARE))
    assert found, "the middleware names one matcher"
    return re.compile("^" + found.group(1) + "$")


# --- the middleware ------------------------------------------------------------------------------------------------

def test_the_middleware_is_at_the_root_of_the_frontend_and_hands_everything_to_the_guard():
    source = read(MIDDLEWARE)
    assert MIDDLEWARE.parent == FRONTEND  # where Next looks for it
    assert "import { guard } from './server/ui-login.mjs'" in source
    assert "await guard(request, process.env)" in source and "NextResponse.next()" in source
    assert source.index("guard(") < source.index("NextResponse.next()")
    assert "return turnedAway ?? NextResponse.next()" in source  # what the guard turned away is what is returned
    assert "export async function middleware(request)" in source


def test_the_matcher_covers_every_page_and_route_but_only_the_framework_s_static_files():
    pattern = matcher()
    for path in ["/", "/tasks", "/memory", "/login", "/session", "/api/chat", "/api/memory/3/accept", "/_next/webpack-hmr", "/__nextjs_original-stack-frame",
                 "/_next/data/x.json", "/apple-touch-icon.png", "/robots.txt"]:
        assert pattern.match(path), path  # the guard decides these
    for path in ["/_next/static/chunks/main.js", "/_next/image", "/favicon.ico", "/icons/icon-192.png", "/diya-flame.svg"]:
        assert not pattern.match(path), path  # nothing private is in these, and the sign-in page needs them


def test_what_the_matcher_leaves_out_is_what_the_app_ships_publicly_and_nothing_else():
    public = sorted(p.name for p in (FRONTEND / "public").iterdir())
    assert public == ["diya-flame.svg", "icons"]  # a new file here is public: this says so when one appears
    assert {p.suffix for p in (FRONTEND / "public" / "icons").iterdir()} <= {".png", ".svg", ".ico"}


# --- /session and the sign-in page --------------------------------------------------------------------------------------

def test_session_is_served_by_the_login_module_with_the_environment_and_one_counter_for_the_whole_server():
    source = read(SESSION)
    assert "import { handleSession, newLoginState } from '../../server/ui-login.mjs'" in source
    assert "const state = newLoginState()" in source and source.index("const state") < source.index("const handle")
    assert "handleSession(request, process.env, state)" in source
    assert re.findall(r"export const (\w+) = ", source) == ["dynamic", "GET", "POST", "DELETE"]
    assert "force-dynamic" in source


def test_session_is_not_a_stand_in_for_the_python_api():
    assert "app/api" not in str(SESSION.relative_to(FRONTEND)).replace("\\", "/") and "proxy.mjs" not in read(SESSION)


def test_the_sign_in_page_posts_the_passcode_to_session_and_goes_where_the_server_says():
    source = read(LOGIN)
    assert source.startswith("'use client'")
    assert "fetch('/session'" in source and "method: 'POST'" in source and "JSON.stringify({ passcode, next })" in source
    assert "window.location.assign(data.next)" in source and "typeof data.next === 'string'" in source
    assert "new URLSearchParams(window.location.search).get('next')" in source
    assert 'type="password"' in source and 'autoComplete="current-password"' in source
    assert "localStorage" not in source and "sessionStorage" not in source and "console." not in source  # the passcode is kept nowhere
    assert 'role="alert"' in source  # a wrong passcode is announced


def test_the_sign_in_page_says_why_it_failed_in_the_servers_words_or_its_own():
    source = read(LOGIN)
    assert "data && typeof data.error === 'string' ? data.error" in source
    assert "didn’t answer" in source  # the server could not be reached at all
    assert "finally {\n      setBusy(false)" in source  # the button is never left stuck on "Signing in"


def test_the_sign_in_button_cannot_be_pressed_twice_or_empty():
    source = read(LOGIN)
    assert "if (busy || !passcode) return" in source and "disabled={busy || !passcode}" in source


# --- the shell -------------------------------------------------------------------------------------------------------------

def test_the_shell_is_not_drawn_round_the_sign_in_page():
    source = read(SHELL)
    wrapper = source[source.index("export default function AppShell"):source.index("function Shell(")]
    assert "if (pathname === '/login') return <>{children}</>" in wrapper
    assert "useCounts" not in wrapper  # nothing in the shell asks the API before signing in
    assert "<Shell pathname={pathname}>{children}</Shell>" in wrapper


def test_sign_out_is_offered_only_when_sign_in_is_on_and_this_browser_is_signed_in():
    source = read(SHELL)
    part = source[source.index("function SignOut()"):source.index("// The sign-in page is drawn without the shell")]
    assert "fetch('/session')" in part and "setSignedIn(Boolean(data.required && data.signedIn))" in part
    assert "if (!signedIn) return null" in part
    assert "fetch('/session', { method: 'DELETE' })" in part and "window.location.assign('/login')" in part
    assert "finally {\n      window.location.assign('/login')" in part  # leaves the page even if the call did not get through
    assert source.count("<SignOut />") == 1 and source.index("<ThemeToggle />") < source.index("<SignOut />")


def test_a_failed_check_shows_no_button_rather_than_a_wrong_one():
    part = read(SHELL)[read(SHELL).index("function SignOut()"):]
    assert ".catch(() => {\n        if (alive) setSignedIn(false)" in part


# --- the browser never holds the cookie or the passcode ---------------------------------------------------------------

def browser_sources():
    return [p for folder in ("app", "components", "lib") for p in (FRONTEND / folder).rglob("*") if p.suffix in (".js", ".jsx", ".mjs")]


def test_nothing_the_browser_runs_names_the_cookie_or_the_passcode_setting():
    for path in browser_sources():
        source = read(path)
        for forbidden in ("diya_session", "DIYA_UI_PASSCODE", "document.cookie"):
            assert forbidden not in source, (path.name, forbidden)


def test_the_login_module_is_not_in_a_folder_the_browser_bundle_scans():
    assert (FRONTEND / "server" / "ui-login.mjs").is_file()
    assert not any(p.name == "ui-login.mjs" for p in browser_sources())


def test_the_passcode_only_ever_comes_from_the_environment_it_is_handed_and_is_never_logged_or_written():
    source = read(FRONTEND / "server" / "ui-login.mjs")
    assert source.count("process.env") == 0  # it is handed the environment, so a test can hand it another
    assert "DIYA_UI_PASSCODE" in source and "console." not in source and "writeFile" not in source


# --- the styles ---------------------------------------------------------------------------------------------------------------

def test_the_sign_in_page_and_the_button_use_classes_that_exist_and_only_the_themes_variables():
    css = read(CSS)
    for name in (".login ", ".login-card", ".login-title", ".login-label", ".login-input", ".login-problem", ".login-submit", ".signout"):
        assert name in css, name
    block = css[css.index(".signout {"):css.index(".theme-label")]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", block)  # no colour of its own: both themes follow from the variables
    assert "font-size: 16px" in block  # a phone does not zoom in on the field
    page = read(LOGIN)
    for cls in ("login", "login-card", "login-title", "login-label", "login-input", "login-problem", "login-submit"):
        assert cls in page, cls
