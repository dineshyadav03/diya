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
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("DIYA_")}
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


def test_package_json_scripts_name_no_address_or_certificate_file():
    scripts = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["scripts"]
    for name, command in scripts.items():
        assert "0.0.0.0" not in command and ".pem" not in command, name
        assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", command), name
    assert {n for n, c in scripts.items() if "--lan" in c} == {"dev:lan", "start:lan"}
    assert scripts["dev"] == "node tools/next-tls.mjs dev" and scripts["start"] == "node tools/next-tls.mjs start"
