"""Test isolation: no test may reach Diya's live data.

Every test runs in its own empty working directory (so the relative defaults
like `diya.db` and `user_profile.txt` land in a temp dir, never the repo) and
with all DIYA_* variables pointed at that directory. The guard test in
test_config.py pins this down.
"""
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    for name in [n for n in os.environ if n.startswith("DIYA_")]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DIYA_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DIYA_PROFILE_PATH", str(tmp_path / "profile.txt"))
    return tmp_path


@pytest.fixture
def run_python(tmp_path):
    """Run `python -c <code>` in a fresh interpreter, in tmp_path, with the repo importable."""

    def run(code, env=None, timeout=60):
        full_env = {k: v for k, v in os.environ.items() if not k.startswith("DIYA_")}
        full_env["PYTHONPATH"] = str(ROOT)
        full_env.update(env or {})
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=tmp_path,
            env=full_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    return run
