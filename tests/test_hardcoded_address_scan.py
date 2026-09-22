"""scripts/check_hardcoded_addresses.py: the same check CI runs as its own step. Covered here too
so a regression is caught by the ordinary local `pytest` run, not only in CI.
"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location(
    "check_hardcoded_addresses", ROOT / "scripts" / "check_hardcoded_addresses.py"
)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def test_the_repository_itself_has_no_hardcoded_private_network_address():
    assert check.find_problems() == []


def test_a_hardcoded_address_outside_tests_is_caught(tmp_path):
    (tmp_path / "README.md").write_text("Reach it at 192.168.5.5 for testing.\n", encoding="utf-8")
    _init_repo(tmp_path)
    assert check.find_problems(tmp_path) == ["README.md:1: 192.168.5.5"]


@pytest.mark.parametrize("address", ["10.0.0.1", "172.20.3.4", "192.168.1.1"])
def test_all_three_private_ranges_are_caught(tmp_path, address):
    (tmp_path / "note.txt").write_text(f"the box is at {address}\n", encoding="utf-8")
    _init_repo(tmp_path)
    assert check.find_problems(tmp_path) == [f"note.txt:1: {address}"]


def test_the_same_address_inside_tests_is_not_flagged(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_thing.py").write_text('HOST = "10.1.2.3"\n', encoding="utf-8")
    _init_repo(tmp_path)
    assert check.find_problems(tmp_path) == []


def test_a_public_looking_address_is_not_flagged(tmp_path):
    (tmp_path / "readme.md").write_text("example.com resolves to 203.0.113.5.\n", encoding="utf-8")
    _init_repo(tmp_path)
    assert check.find_problems(tmp_path) == []


def test_a_binary_extension_is_skipped_not_read(tmp_path):
    (tmp_path / "image.png").write_bytes(b"\x89PNG fake binary 192.168.1.1")
    _init_repo(tmp_path)
    assert check.find_problems(tmp_path) == []


def _init_repo(root):
    """A minimal git repo so tracked_files() (git ls-files) has something to list."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], cwd=root, check=True)
