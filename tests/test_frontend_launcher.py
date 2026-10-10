"""The frontend's dev/start scripts: loopback by default, LAN only when asked, certificate from the
environment or discovery, and no machine-specific value written into package.json.

The launcher is run through Node with --dry-run (it prints what it would start). It is copied into
a temporary tree first, so it looks for certificates there and never at the real repo root.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "frontend" / "tools" / "next-tls.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "frontend" / "tools").mkdir(parents=True)
    shutil.copy(LAUNCHER, tmp_path / "frontend" / "tools" / "next-tls.mjs")
    return tmp_path


LOGIN = {"DIYA_UI_PASSCODE": "a passcode of some length"}  # what LAN mode now requires (docs/UI_LOGIN_DESIGN.md); the tests that are about something else pass it
QUIET = {"NEXT_TELEMETRY_DISABLED": "1"}  # what the launcher adds to the UI server's environment (audit F4)


def pair(folder, name="localhost+2"):
    (folder / f"{name}.pem").write_text("cert")
    (folder / f"{name}-key.pem").write_text("key")


def launch(tree, *argv, env=None):
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("DIYA_") and k != "NODE_OPTIONS"}
    full_env.update(env or {})
    result = subprocess.run(
        ["node", str(tree / "frontend" / "tools" / "next-tls.mjs"), *argv, "--dry-run"],
        capture_output=True, text=True, env=full_env, timeout=30,
    )
    plan = json.loads(result.stdout) if result.returncode == 0 else None
    return result, plan


def test_dev_listens_on_loopback_with_the_discovered_certificate(tree):
    pair(tree)
    result, plan = launch(tree, "dev")
    assert result.returncode == 0, result.stderr
    assert (plan["host"], plan["port"], plan["lan"]) == ("127.0.0.1", "3000", False)
    args = plan["args"]
    assert args[args.index("-H") + 1] == "127.0.0.1"
    assert args[args.index("--experimental-https-cert") + 1] == str(tree / "localhost+2.pem")
    assert args[args.index("--experimental-https-key") + 1] == str(tree / "localhost+2-key.pem")
    assert "0.0.0.0" not in args


def test_lan_mode_is_only_what_the_lan_flag_asks_for(tree):
    pair(tree)
    _, plan = launch(tree, "dev", "--lan", env=LOGIN)
    assert (plan["host"], plan["lan"]) == ("0.0.0.0", True)
    _, plain = launch(tree, "dev")
    assert plain["host"] == "127.0.0.1"


def test_the_certificate_can_come_from_the_environment(tree):
    pair(tree, "a+1")
    pair(tree, "b+1")  # two discoverable pairs would be an error; the environment settles it
    (tree / "certs").mkdir()
    (tree / "certs" / "c.pem").write_text("c")
    (tree / "certs" / "k.pem").write_text("k")
    result, plan = launch(tree, "dev", env={"DIYA_SSL_CERT": "certs/c.pem", "DIYA_SSL_KEY": "certs/k.pem"})
    assert result.returncode == 0, result.stderr
    args = plan["args"]  # relative paths are read from the repo root, where the backend runs
    assert args[args.index("--experimental-https-cert") + 1] == str(tree / "certs" / "c.pem")
    assert args[args.index("--experimental-https-key") + 1] == str(tree / "certs" / "k.pem")


@pytest.mark.parametrize("env", [{"DIYA_SSL_CERT": "c.pem"}, {"DIYA_SSL_KEY": "k.pem"}])
def test_a_lone_certificate_setting_is_refused(tree, env):
    pair(tree)
    result, _ = launch(tree, "dev", env=env)
    assert result.returncode == 1 and "must be set together" in result.stderr


def test_a_missing_certificate_file_is_reported(tree):
    result, _ = launch(tree, "dev", env={"DIYA_SSL_CERT": "no.pem", "DIYA_SSL_KEY": "no-key.pem"})
    assert result.returncode == 1 and "TLS file not found" in result.stderr


def test_no_certificate_says_how_to_make_one(tree):
    result, _ = launch(tree, "dev")
    assert result.returncode == 1 and "mkcert" in result.stderr


def test_two_certificate_pairs_are_an_error_not_a_guess(tree):
    pair(tree, "a+1")
    pair(tree, "b+2")
    result, _ = launch(tree, "dev")
    assert result.returncode == 1
    assert "more than one mkcert certificate" in result.stderr and "a+1.pem" in result.stderr and "b+2.pem" in result.stderr


def test_the_port_follows_the_setting_the_backend_uses_for_this_origin(tree):
    pair(tree)
    _, plan = launch(tree, "dev", env={"DIYA_FRONTEND_PORT": "4443"})
    assert plan["args"][plan["args"].index("-p") + 1] == "4443"
    for bad in ("abc", "0", "70000"):
        result, _ = launch(tree, "dev", env={"DIYA_FRONTEND_PORT": bad})
        assert result.returncode == 1 and "DIYA_FRONTEND_PORT" in result.stderr


def test_start_needs_no_certificate_and_is_loopback_too(tree):
    result, plan = launch(tree, "start")
    assert result.returncode == 0, result.stderr
    assert plan["args"] == ["start", "-H", "127.0.0.1", "-p", "3000"]
    assert launch(tree, "start", "--lan", env=LOGIN)[1]["args"][2] == "0.0.0.0"


def test_an_unknown_mode_is_refused(tree):
    result, _ = launch(tree, "build")
    assert result.returncode == 1 and "usage" in result.stderr


def node_reads_the_system_trust_store():
    """Whether this Node has --use-system-ca (22.15+/23.9+): the launcher only adds what it has."""
    found = subprocess.run(
        ["node", "-p", "process.allowedNodeEnvironmentFlags.has('--use-system-ca')"], capture_output=True, text=True
    )
    return found.stdout.strip() == "true"


SYSTEM_CA = node_reads_the_system_trust_store()
needs_system_ca = pytest.mark.skipif(not SYSTEM_CA, reason="this Node has no --use-system-ca")


@pytest.mark.parametrize("argv", [("dev",), ("dev", "--lan"), ("start",), ("start", "--lan")])
def test_the_ui_server_is_started_trusting_the_system_certificate_store(tree, argv):
    """Its own HTTPS calls to the API (app/api) must verify an mkcert certificate; Node ignores
    the OS trust store, where mkcert puts its root, unless asked -- and is never handed a flag it
    does not know."""
    pair(tree)
    _, plan = launch(tree, *argv, env=LOGIN)
    assert plan["env"] == {**({"NODE_OPTIONS": "--use-system-ca"} if SYSTEM_CA else {}), **QUIET}


@needs_system_ca
def test_an_existing_node_options_is_kept_and_the_flag_is_not_added_twice(tree):
    pair(tree)
    _, plan = launch(tree, "dev", env={"NODE_OPTIONS": "--max-old-space-size=512"})
    assert plan["env"] == {"NODE_OPTIONS": "--max-old-space-size=512 --use-system-ca", **QUIET}
    _, plan = launch(tree, "dev", env={"NODE_OPTIONS": "--use-system-ca --max-old-space-size=512"})
    assert plan["env"] == QUIET  # already there: nothing to change


def test_lan_mode_differs_from_loopback_only_in_the_interface_it_listens_on(tree):
    """The proxy adds nothing to LAN mode: the UI server is the same in both, on a wider interface,
    and no name or address of the other device is baked in anywhere."""
    pair(tree)
    _, loopback = launch(tree, "dev")
    _, lan = launch(tree, "dev", "--lan", env=LOGIN)
    assert loopback["env"] == lan["env"]
    assert [a for a in loopback["args"] if a != "127.0.0.1"] == [a for a in lan["args"] if a != "0.0.0.0"]
    assert not re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", json.dumps(lan).replace("0.0.0.0", ""))


def test_the_launcher_never_carries_the_access_token(tree):
    pair(tree)
    result, _ = launch(tree, "dev", env={"DIYA_TOKEN": "not-a-real-token-1234567890"})
    assert result.returncode == 0 and "not-a-real-token" not in result.stdout + result.stderr


def real_start(tree, *argv, env=None):
    """Run the launcher for real (not --dry-run) against a stand-in for `next` that reports how it
    was started, so what the child process actually receives is checked, not just what is planned."""
    stub = tree / "frontend" / "node_modules" / "next" / "dist" / "bin" / "next"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text("console.log(JSON.stringify({args: process.argv.slice(2), node_options: process.env.NODE_OPTIONS ?? null, token: process.env.DIYA_TOKEN ?? null}))")
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("DIYA_") and k != "NODE_OPTIONS"}
    full_env.update(env or {})
    result = subprocess.run(
        ["node", str(tree / "frontend" / "tools" / "next-tls.mjs"), *argv], capture_output=True, text=True, env=full_env, timeout=30
    )
    return result, (json.loads(result.stdout) if result.returncode == 0 else None)


@needs_system_ca
def test_the_ui_server_process_really_receives_the_trust_flag(tree):
    pair(tree)
    result, child = real_start(tree, "dev", env={"DIYA_TOKEN": "t-1234567890abcdefghij"})
    assert result.returncode == 0, result.stderr
    assert child["node_options"] == "--use-system-ca"
    assert child["token"] == "t-1234567890abcdefghij"  # the environment is inherited: this is how DIYA_TOKEN reaches the routes
    assert child["args"][0] == "dev"


def test_lan_mode_says_the_api_needs_no_lan_mode_for_the_ui(tree):
    pair(tree)
    result, _ = real_start(tree, "dev", "--lan", env=LOGIN)
    assert "the API needs neither DIYA_LAN nor DIYA_ALLOWED_HOSTS for the UI" in " ".join(result.stderr.split())
    quiet, _ = real_start(tree, "dev")
    assert "LAN mode" not in quiet.stderr


HINT = "DIYA_TOKEN is not set for the UI"
FAKE_TOKEN = "not-a-real-token-1234567890"


def test_starting_the_ui_without_a_token_says_the_api_will_refuse_it(tree):
    """The API requires the token by default, so a UI with none gets 401 on everything: say so at
    startup, and how to get one, instead of leaving only a puzzling "didn't send" in the browser."""
    pair(tree)
    result, _ = real_start(tree, "dev")
    text = " ".join(result.stderr.split())
    assert HINT in text and "frontend/.env.local" in text and "--rotate-token" in text


@pytest.mark.parametrize("where", ["environment", ".env.local", ".env"])
def test_no_hint_when_the_ui_has_a_token(tree, where):
    pair(tree)
    env = {}
    if where == "environment":
        env = {"DIYA_TOKEN": FAKE_TOKEN}
    else:
        (tree / "frontend" / where).write_text(f"OTHER=1\nDIYA_TOKEN={FAKE_TOKEN}\n")
    result, _ = real_start(tree, "dev", env=env)
    assert result.returncode == 0 and HINT not in result.stderr and FAKE_TOKEN not in result.stderr


@pytest.mark.parametrize("line", ["# DIYA_TOKEN=abc123", "DIYA_TOKEN=", "DIYA_TOKEN =   ", "NOT_DIYA_TOKEN=abc123"])
def test_a_commented_out_or_empty_token_line_is_not_a_token(tree, line):
    pair(tree)
    (tree / "frontend" / ".env.local").write_text(line + "\n")
    result, _ = real_start(tree, "dev")
    assert HINT in " ".join(result.stderr.split())


@pytest.mark.parametrize("word", ["0", "false", "off", "no", "OFF"])
def test_no_hint_when_the_requirement_is_opted_out(tree, word):
    pair(tree)
    result, _ = real_start(tree, "dev", env={"DIYA_REQUIRE_TOKEN": word})
    assert HINT not in result.stderr


def test_package_json_scripts_name_no_address_or_certificate_file():
    scripts = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["scripts"]
    for name, command in scripts.items():
        assert "0.0.0.0" not in command and ".pem" not in command, name
        assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", command), name
    assert {n for n, c in scripts.items() if "--lan" in c} == {"dev:lan", "start:lan"}
    assert scripts["dev"] == "node tools/next-tls.mjs dev" and scripts["start"] == "node tools/next-tls.mjs start"


# --- the passcode that protects the UI (docs/UI_LOGIN_DESIGN.md) -----------------------------------------------------

GOOD = "a passcode of some length"  # at least 12 characters


def test_lan_mode_will_not_start_without_a_passcode(tree):
    pair(tree)
    result, plan = launch(tree, "dev", "--lan")
    assert result.returncode == 1 and plan is None
    assert "LAN mode needs a passcode" in result.stderr and "DIYA_UI_PASSCODE" in result.stderr and "12 characters" in result.stderr


@pytest.mark.parametrize("passcode", ["short", "elevenchars", "   padded   ", ""])
def test_lan_mode_will_not_start_with_a_passcode_that_is_too_short(tree, passcode):
    pair(tree)
    result, plan = launch(tree, "dev", "--lan", env={"DIYA_UI_PASSCODE": passcode})
    assert result.returncode == 1 and plan is None and "LAN mode needs a passcode" in result.stderr
    assert passcode.strip() == "" or passcode.strip() not in result.stderr  # what was typed is never repeated


def test_lan_mode_starts_with_a_passcode_of_twelve_characters_or_more_and_says_a_login_is_on(tree):
    pair(tree)
    for passcode in ("twelve chars", GOOD):
        result, plan = launch(tree, "dev", "--lan", env={"DIYA_UI_PASSCODE": passcode})
        assert result.returncode == 0, result.stderr
        assert plan["lan"] is True and plan["login"] is True and passcode not in result.stdout


def test_without_lan_mode_no_passcode_is_needed_and_the_plan_says_there_is_no_login(tree):
    pair(tree)
    result, plan = launch(tree, "dev")
    assert result.returncode == 0 and plan["login"] is False


def test_a_short_passcode_is_allowed_without_lan_mode(tree):
    pair(tree)
    result, plan = launch(tree, "dev", env={"DIYA_UI_PASSCODE": "short"})
    assert result.returncode == 0 and plan["login"] is True


@pytest.mark.parametrize("line, expected", [
    (f"DIYA_UI_PASSCODE={GOOD}", True),
    (f"DIYA_UI_PASSCODE = {GOOD}", True),
    (f'DIYA_UI_PASSCODE="{GOOD}"', True),
    (f"DIYA_UI_PASSCODE='{GOOD}'", True),
    (f"DIYA_UI_PASSCODE={GOOD} # my phone", True),
    ("DIYA_UI_PASSCODE=short # but a long comment follows it", False),
    ('DIYA_UI_PASSCODE="tenchars10"', False),    # ten characters between quotes: the quotes are not part of it
    ("DIYA_UI_PASSCODE='tenchars10'", False),
    ('DIYA_UI_PASSCODE="twelve chars"', True),
    ("DIYA_UI_PASSCODE='twelve chars'", True),
    ('DIYA_UI_PASSCODE="short"', False),
    ("DIYA_UI_PASSCODE=", False),
    (f"# DIYA_UI_PASSCODE={GOOD}", False),
    (f"NOT_DIYA_UI_PASSCODE={GOOD}", False),
    (f"DIYA_TOKEN={GOOD}", False),
])
def test_the_passcode_can_be_kept_in_the_env_file_next_loads_and_is_read_the_way_it_will_be(tree, line, expected):
    pair(tree)
    (tree / "frontend" / ".env.local").write_text("OTHER=1\n" + line + "\nMORE=2\n", encoding="utf-8")
    result, plan = launch(tree, "dev", "--lan")
    assert (result.returncode == 0) is expected, (result.stdout, result.stderr)
    assert GOOD not in result.stdout + result.stderr or expected  # never echoed when refused


def test_the_environment_wins_over_the_env_file(tree):
    pair(tree)
    (tree / "frontend" / ".env.local").write_text("DIYA_UI_PASSCODE=short\n", encoding="utf-8")
    result, plan = launch(tree, "dev", "--lan", env={"DIYA_UI_PASSCODE": GOOD})
    assert result.returncode == 0 and plan["login"] is True


def test_the_minimum_length_is_the_same_number_in_the_launcher_and_in_the_login_module():
    launcher = re.search(r"const MIN_PASSCODE = (\d+)", LAUNCHER.read_text(encoding="utf-8")).group(1)
    module = re.search(r"export const MIN_PASSCODE = (\d+)", (ROOT / "frontend" / "server" / "ui-login.mjs").read_text(encoding="utf-8")).group(1)
    assert launcher == module == "12"


# --- the UI does not report usage to its framework's makers (audit F4) -------------------------------------------------

def test_next_is_told_not_to_report_usage(tree):
    pair(tree)
    result, plan = launch(tree, "dev")
    assert plan["env"]["NEXT_TELEMETRY_DISABLED"] == "1"


def test_the_ui_server_process_really_receives_the_switch(tree):
    pair(tree)
    stub = tree / "frontend" / "node_modules" / "next" / "dist" / "bin" / "next"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text("console.log(JSON.stringify({telemetry: process.env.NEXT_TELEMETRY_DISABLED ?? null, passcode: process.env.DIYA_UI_PASSCODE ?? null}))")
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("DIYA_") and k not in ("NODE_OPTIONS", "NEXT_TELEMETRY_DISABLED")}
    full_env.update(LOGIN)
    result = subprocess.run(["node", str(tree / "frontend" / "tools" / "next-tls.mjs"), "dev"], capture_output=True, text=True, env=full_env, timeout=30)
    child = json.loads(result.stdout.splitlines()[-1])
    assert child == {"telemetry": "1", "passcode": LOGIN["DIYA_UI_PASSCODE"]}  # the passcode reaches the server it protects, the way the token does
    assert LOGIN["DIYA_UI_PASSCODE"] not in result.stderr  # and is not printed by the launcher


def test_a_person_who_set_it_themselves_is_not_overruled(tree):
    pair(tree)
    result, plan = launch(tree, "dev", env={"NEXT_TELEMETRY_DISABLED": "0"})
    assert "NEXT_TELEMETRY_DISABLED" not in plan["env"]


@pytest.mark.parametrize("name", [".env.local", ".env.development.local", ".env.development", ".env"])
def test_every_env_file_next_loads_is_looked_in_for_the_passcode(tree, name):
    pair(tree)
    (tree / "frontend" / name).write_text(f"DIYA_UI_PASSCODE={GOOD}\n", encoding="utf-8")
    result, plan = launch(tree, "dev", "--lan")
    assert result.returncode == 0 and plan["login"] is True


@pytest.mark.parametrize("name", [".env.production", ".env.test", "env.local", ".env.local.bak"])
def test_a_file_next_does_not_load_for_dev_is_not_where_the_passcode_is_looked_for(tree, name):
    pair(tree)
    (tree / "frontend" / name).write_text(f"DIYA_UI_PASSCODE={GOOD}\n", encoding="utf-8")
    assert launch(tree, "dev", "--lan")[0].returncode == 1


def test_a_short_passcode_without_lan_mode_is_warned_about_and_never_repeated(tree):
    pair(tree)
    result, child = real_start(tree, "dev", env={"DIYA_UI_PASSCODE": "tiny one"})
    assert result.returncode == 0
    assert "shorter than 12 characters" in result.stderr and "tiny one" not in result.stderr + result.stdout
    quiet, _ = real_start(tree, "dev", env={"DIYA_UI_PASSCODE": GOOD})
    assert "shorter than" not in quiet.stderr and "asks for a passcode" in quiet.stderr
    none, _ = real_start(tree, "dev")
    assert "asks for a passcode" not in none.stderr
