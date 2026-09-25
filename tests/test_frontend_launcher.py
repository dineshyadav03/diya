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
    _, plan = launch(tree, "dev", "--lan")
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
    assert launch(tree, "start", "--lan")[1]["args"][2] == "0.0.0.0"


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
    _, plan = launch(tree, *argv)
    assert plan["env"] == ({"NODE_OPTIONS": "--use-system-ca"} if SYSTEM_CA else {})


@needs_system_ca
def test_an_existing_node_options_is_kept_and_the_flag_is_not_added_twice(tree):
    pair(tree)
    _, plan = launch(tree, "dev", env={"NODE_OPTIONS": "--max-old-space-size=512"})
    assert plan["env"] == {"NODE_OPTIONS": "--max-old-space-size=512 --use-system-ca"}
    _, plan = launch(tree, "dev", env={"NODE_OPTIONS": "--use-system-ca --max-old-space-size=512"})
    assert plan["env"] == {}  # already there: nothing to change


def test_lan_mode_differs_from_loopback_only_in_the_interface_it_listens_on(tree):
    """The proxy adds nothing to LAN mode: the UI server is the same in both, on a wider interface,
    and no name or address of the other device is baked in anywhere."""
    pair(tree)
    _, loopback = launch(tree, "dev")
    _, lan = launch(tree, "dev", "--lan")
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
    result, _ = real_start(tree, "dev", "--lan")
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
