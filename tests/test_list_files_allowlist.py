"""list_files (diya.py) and its configuration (diya_config.py): Stage 1 design, Unit 1
(docs/STAGE1_DESIGN.md, section 5 and the "Rollout plan" -> "list_files allowlist and secret
filtering"). Deny by default outside a configured root, os.path.realpath (not just normpath) so a
symlink escape is caught the same way a plain ../ escape is, and secret-shaped names filtered out
even from an allowed directory.
"""
import os
import pathlib

import pytest

import diya
import diya_config
from diya_config import ConfigError, load_config
from fakes import FakeClient


def _touch(path):
    pathlib.Path(path).touch()


@pytest.fixture
def root(tmp_path):
    """An allowed root with a normal file, secret-shaped entries, and a real subfolder."""
    r = tmp_path / "root"
    r.mkdir()
    _touch(r / "note.txt")
    _touch(r / ".env")
    _touch(r / ".env.local")
    _touch(r / ".hidden")
    (r / ".ssh").mkdir()
    _touch(r / "server.pem")
    _touch(r / "id.key")
    sub = r / "sub"
    sub.mkdir()
    _touch(sub / "a.txt")
    return r


@pytest.fixture
def outside(tmp_path):
    o = tmp_path / "outside"
    o.mkdir()
    _touch(o / "secret.txt")
    return o


# --- 1. a path outside every configured root is refused, absolute and ../-relative --------------

def test_an_absolute_path_outside_every_root_is_refused(root, outside):
    result = diya.list_files(str(outside), roots=(str(root),))
    assert result == f"Can't list '{outside}': outside the allowed folders."


def test_a_dot_dot_relative_escape_is_refused(root, outside):
    escape = os.path.join("..", outside.name)
    result = diya.list_files(escape, roots=(str(root),))
    assert result == f"Can't list '{escape}': outside the allowed folders."
    assert "secret.txt" not in result


def test_no_roots_at_all_denies_everything_deny_by_default(root):
    assert diya.list_files(".", roots=()) == "Can't list '.': outside the allowed folders."
    assert diya.list_files(str(root), roots=()) == f"Can't list '{root}': outside the allowed folders."


def test_the_roots_parameter_defaults_to_empty_not_the_whole_filesystem():
    """A direct call that forgets to pass roots must not fall back to os.listdir(directory)."""
    result = diya.list_files(".")
    assert result == "Can't list '.': outside the allowed folders."


# --- 2. a symlink inside an allowed root that points outside it is refused ----------------------

def test_realpath_not_normpath_drives_the_containment_check(root, outside, monkeypatch):
    """A plain ../ escape is resolved correctly by both normpath and realpath alike (neither needs
    the filesystem for that) -- only a case where they'd disagree, like a symlink, actually proves
    which one the code uses. Mocked here so the property is verified regardless of whether this
    machine/user is allowed to create real symlinks (Windows requires elevation or Developer Mode;
    verified directly on this machine: plain os.symlink() raises "a required privilege is not
    held"). test_a_real_symlink_escape_is_refused below additionally proves it with a genuine
    symlink wherever the environment permits creating one.
    """
    real_realpath = os.path.realpath

    def fake_realpath(path):
        # Simulate root/sub being a symlink to `outside` -- normpath would never know this.
        if os.path.normpath(path) == os.path.normpath(str(root / "sub")):
            return str(outside)
        return real_realpath(path)

    monkeypatch.setattr(diya.os.path, "realpath", fake_realpath)
    result = diya.list_files("sub", roots=(str(root),))
    assert result == "Can't list 'sub': outside the allowed folders."


@pytest.mark.skipif(os.name == "nt", reason="creating a symlink on Windows needs elevation or Developer Mode")
def test_a_real_symlink_escape_is_refused(root, outside):
    link = root / "escape"
    os.symlink(outside, link, target_is_directory=True)
    result = diya.list_files("escape", roots=(str(root),))
    assert result == "Can't list 'escape': outside the allowed folders."


def test_a_real_symlink_escape_is_refused_on_windows_when_creation_is_permitted(root, outside):
    """Same as above, attempted for real on Windows too -- skipped only if this account genuinely
    can't create symlinks (the common case without admin/Developer Mode), not skipped outright."""
    if os.name != "nt":
        pytest.skip("covered by the cross-platform test above")
    link = root / "escape"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"this account can't create symlinks: {exc}")
    result = diya.list_files("escape", roots=(str(root),))
    assert result == "Can't list 'escape': outside the allowed folders."


# --- 3. secret-shaped entries are filtered from an allowed directory's own listing ---------------

def test_dotfiles_and_secret_extensions_are_filtered_from_an_allowed_directory(root):
    result = set(diya.list_files(".", roots=(str(root),)).split("\n"))
    assert result == {"note.txt", "sub"}  # everything else in the fixture is secret-shaped
    for hidden in (".env", ".env.local", ".hidden", ".ssh", "server.pem", "id.key"):
        assert hidden not in result


def test_filtering_applies_per_entry_not_only_to_the_root_check():
    """Kills a mutation that only guards the root-containment check and never actually filters
    the listing -- i.e. asserting the secret names are truly absent from the *result*, not just
    that the allowed directory itself was reachable (the previous test already shows both, but a
    minimal, single-purpose repro of just this property makes the mutation this guards against
    unambiguous)."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        _touch(os.path.join(d, "visible.txt"))
        _touch(os.path.join(d, ".env"))
        result = diya.list_files(".", roots=(d,))
        assert "visible.txt" in result
        assert ".env" not in result


# --- 4. a legitimate subfolder of the root still lists normally ---------------------------------

def test_a_legitimate_subfolder_lists_normally(root):
    assert diya.list_files("sub", roots=(str(root),)) == "a.txt"


def test_an_absolute_path_already_inside_a_root_is_accepted(root):
    sub = root / "sub"
    assert diya.list_files(str(sub), roots=(str(root),)) == "a.txt"


def test_the_root_itself_is_listable_not_only_its_subfolders(root):
    result = set(diya.list_files(".", roots=(str(root),)).split("\n"))
    assert {"note.txt", "sub"} == result


def test_multiple_roots_the_first_matching_one_is_used(root, outside, tmp_path):
    another = tmp_path / "another"
    another.mkdir()
    _touch(another / "x.txt")
    assert diya.list_files(".", roots=(str(root), str(another))) != f"Can't list '.': outside the allowed folders."
    # a directory only the second root can see is still reachable
    assert diya.list_files(str(another), roots=(str(root), str(another))) == "x.txt"


# --- configuration: DIYA_FILES_ROOTS, same shape as DIYA_ALLOWED_HOSTS, adapted for paths --------

def test_no_files_roots_configured_means_the_default_folder_only():
    config = load_config({})
    assert config.files_roots == ()
    assert diya_config.resolved_files_roots(config) == (diya_config.default_files_root(),)


def test_the_default_folder_is_documents_diya_under_the_home_directory():
    expected = os.path.join(os.path.expanduser("~"), "Documents", "Diya")
    assert diya_config.default_files_root() == expected


def test_configured_roots_replace_the_default_they_do_not_add_to_it():
    config = load_config({"DIYA_FILES_ROOTS": "C:\\notes"})
    assert diya_config.resolved_files_roots(config) == ("C:\\notes",)
    assert diya_config.default_files_root() not in diya_config.resolved_files_roots(config)


def test_files_roots_are_comma_split_stripped_and_deduplicated_but_not_lowercased():
    config = load_config({"DIYA_FILES_ROOTS": " C:\\Notes , C:\\Docs ,, C:\\Notes ,"})
    assert config.files_roots == ("C:\\Notes", "C:\\Docs")  # case preserved, unlike host names


def test_blank_files_roots_counts_as_unset():
    assert load_config({"DIYA_FILES_ROOTS": "   "}).files_roots == ()


def test_files_roots_needs_no_special_validation_paths_may_contain_colons_and_backslashes():
    # Unlike DIYA_ALLOWED_HOSTS, a path legitimately contains characters a host name never would.
    config = load_config({"DIYA_FILES_ROOTS": "C:\\Users\\me\\Documents\\Diya"})
    assert config.files_roots == ("C:\\Users\\me\\Documents\\Diya",)


# --- Agent wiring: the real tool is bound with the real, resolved roots -------------------------

def test_agent_binds_list_files_to_the_configured_roots(tmp_path):
    config_root = tmp_path / "configured"
    config_root.mkdir()
    _touch(config_root / "a.txt")
    config = diya_config.Config(
        db_path=str(tmp_path / "a.db"), files_roots=(str(config_root),)
    )
    agent = diya.Agent(config, client=FakeClient())
    bound = agent._functions["list_files"]
    assert bound(directory=".") == "a.txt"
    assert bound(directory=str(tmp_path)) == f"Can't list '{tmp_path}': outside the allowed folders."


def test_agent_uses_the_default_folder_when_nothing_is_configured(tmp_path):
    config = diya_config.Config(db_path=str(tmp_path / "a.db"))  # files_roots left at the default ()
    agent = diya.Agent(config, client=FakeClient())
    bound = agent._functions["list_files"]
    # Whatever the default resolves to, it is never this repo's own directory -- a real install's
    # source code must not be reachable through the tool just because nothing was configured.
    repo_root = os.path.dirname(os.path.abspath(diya.__file__))
    assert bound(directory=repo_root) == f"Can't list '{repo_root}': outside the allowed folders."


# --- the tool schema tells the model about the restriction, not the old unrestricted claim -------

def test_the_tool_description_no_longer_claims_unrestricted_access():
    spec = next(t for t in diya.TOOLS if t["function"]["name"] == "list_files")
    description = spec["function"]["description"].lower()
    assert description != "list the files in a directory on this computer."  # the old, unrestricted claim
    assert "allowed" in description or "configured" in description
