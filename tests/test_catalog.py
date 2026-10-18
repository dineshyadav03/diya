"""The side-effect catalog keeps its promise (diya_catalog.py, docs/AUTHORITY_MODEL.md), added 2026-10-18 for DIYA-036, -037 and -038.

What this proves, by looking at the code itself and not at a description of it: every tool the model can be offered, every kind of action and every flow the code decides on has an entry that says what it
touches, how it is undone and who must agree; nothing in the catalog is stale; the tier matches the way the thing works (a model-callable tool never changes anything at a service, and anything at tier 2 or
above is a proposal the owner approves); the only code that can send something out is named, with a reason; the Google and Todoist requests are made only from the functions that run after an approval; the
only place an approved action is executed is diya_actions.run; and the generated document is current. A new capability that skips any of this fails here.
"""
import ast
import dataclasses
import pathlib
import re

import pytest

import diya
import diya_actions
import diya_catalog as catalog
import diya_config
import diya_connector_tools

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "c.db"), connector_tokens_dir=str(tmp_path / "t"), connectors_log_path=str(tmp_path / "l"))


def project_modules():
    skip = ("milestone", "build_pdf", "render_", "dossier", "localhost")
    return [p for p in sorted(ROOT.glob("*.py")) if not p.name.startswith(skip)]


def real_names(config):
    tools = {t["function"]["name"] for t in diya.TOOLS} | {spec["function"]["name"] for _c, spec, _f in diya_connector_tools.tool_specs(config)}
    proposals = {kind.tool_name for kind in diya_connector_tools.real_action_kinds() if kind.tool is not None}
    return tools, proposals


def flow_names():
    """The names the agent journals with kind="flow": found in the source, so a new flow cannot be added unseen."""
    tree = ast.parse((ROOT / "diya.py").read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_journal":
            if any(k.arg == "kind" and isinstance(k.value, ast.Constant) and k.value.value == "flow" for k in node.keywords) and node.args:
                first = node.args[0]
                found |= {c.value for c in ast.walk(first) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return found


# ---- the catalog is complete and not stale ----------------------------------------------------------------------------------------------------

def test_every_tool_and_proposal_the_model_can_be_offered_has_an_entry_of_the_right_type(config):
    tools, proposals = real_names(config)
    missing = (tools | proposals) - set(catalog.CATALOG)
    assert not missing, f"add these to diya_catalog.CATALOG: {sorted(missing)}"
    assert all(catalog.CATALOG[name].type == "tool" for name in tools) and all(catalog.CATALOG[name].type == "proposal" for name in proposals)


def test_every_flow_the_agent_journals_has_an_entry(config):
    flows = flow_names()
    assert flows >= {"read_mail", "study_repo", "explain_memory", "mail_write_refused", "search_notes", "web_search"}
    undeclared = {name for name in flows if name not in catalog.CATALOG}
    assert not undeclared, f"add these flows to diya_catalog.CATALOG: {sorted(undeclared)}"
    assert all(catalog.CATALOG[name].type == "flow" for name in flows - catalog.SHARED_FLOW_NAMES)


def test_nothing_in_the_catalog_is_stale(config):
    tools, proposals = real_names(config)
    real = tools | proposals | flow_names()
    stale = set(catalog.CATALOG) - real
    assert not stale, f"these are in the catalog but no longer exist: {sorted(stale)}"


def test_every_entry_is_filled_in_properly():
    for entry in catalog.CATALOG.values():
        assert entry.type in ("tool", "proposal", "flow") and entry.tier in catalog.TIERS and entry.effect.strip() and entry.network.strip() and entry.reversible.strip()
        assert entry.approval in ("none", "owner approves each action")


# ---- the tier matches how the thing works ------------------------------------------------------------------------------------------------------

def test_a_tool_the_model_calls_never_changes_anything_at_a_service():
    for entry in catalog.CATALOG.values():
        if entry.type == "tool":
            assert entry.tier <= 1 and entry.approval == "none", entry.name


def test_anything_at_tier_two_or_above_is_a_proposal_the_owner_approves_each_time():
    for entry in catalog.CATALOG.values():
        if entry.tier >= 2:
            assert entry.type == "proposal" and entry.approval == "owner approves each action", entry.name
    assert all(entry.tier >= 2 for entry in catalog.CATALOG.values() if entry.type == "proposal")
    assert max(entry.tier for entry in catalog.CATALOG.values()) == 2  # nothing external-facing or destructive exists yet


def test_a_read_that_returns_other_peoples_words_says_so():
    for name in ("list_files", "search_notes", "web_search", "read_mail", "study_repo", "list_calendar_events", "list_todoist_tasks", "search_notion", "list_google_tasks"):
        assert catalog.CATALOG[name].untrusted_output, name
    assert not catalog.CATALOG["explain_memory"].untrusted_output


def test_every_proposal_is_guarded_by_the_owners_own_words_and_says_it_only_proposes():
    for kind in diya_connector_tools.real_action_kinds():
        assert kind.asked is not None, kind.name  # refused unless the latest message asks for exactly this
        assert "only PROPOSES" in kind.tool["function"]["description"] and "approves it on the Actions page" in kind.tool["function"]["description"], kind.name
        assert kind.connector, kind.name


def test_no_tool_the_model_can_call_takes_an_address_a_header_or_a_credential(config):
    forbidden = {"url", "uri", "host", "endpoint", "token", "access_token", "refresh_token", "authorization", "headers", "api_key", "secret", "base_url"}
    specs = list(diya.TOOLS) + [spec for _c, spec, _f in diya_connector_tools.tool_specs(config)] + [k.tool for k in diya_connector_tools.real_action_kinds()]
    for spec in specs:
        assert not forbidden & set(spec["function"]["parameters"].get("properties", {})), spec["function"]["name"]


# ---- the only code that can send something out ------------------------------------------------------------------------------------------------

def test_the_modules_that_can_send_something_out_are_exactly_the_declared_ones():
    pattern = re.compile(r"\bhttpx\.(?:post|put|patch|delete|request)\(")
    found = {path.name for path in project_modules() if pattern.search(path.read_text(encoding="utf-8"))}
    assert found == set(catalog.OUTBOUND_WRITERS), (
        f"a module that sends data out must be named in diya_catalog.OUTBOUND_WRITERS with its reason: new {sorted(found - set(catalog.OUTBOUND_WRITERS))}, gone {sorted(set(catalog.OUTBOUND_WRITERS) - found)}"
    )


def enclosing_functions(path, matcher):
    """The names of the functions (innermost) that contain a call for which `matcher(call)` is true."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()

    def visit(node, stack):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack = stack + [node.name]
        if isinstance(node, ast.Call) and matcher(node):
            names.add(stack[-1] if stack else "<module>")
        for child in ast.iter_child_nodes(node):
            visit(child, stack)

    visit(tree, [])
    return names


def calls_attr(*pairs):
    def match(call):
        return isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and (call.func.value.id, call.func.attr) in pairs

    return match


def test_google_requests_are_made_only_by_send_and_send_is_called_only_from_the_functions_that_run_after_an_approval():
    path = ROOT / "diya_google_write.py"
    assert enclosing_functions(path, calls_attr(("httpx", "request"))) == {"_send"}
    callers = enclosing_functions(path, lambda call: isinstance(call.func, ast.Name) and call.func.id == "_send")
    assert callers == {"event_execute", "task_execute", "folder_execute", "doc_execute", "_read_back"}, callers  # _read_back only asks for the new thing again (a GET)
    read_back_callers = enclosing_functions(path, lambda call: isinstance(call.func, ast.Name) and call.func.id == "_read_back")
    assert read_back_callers and all(name.endswith("_execute") for name in read_back_callers), read_back_callers
    source = path.read_text(encoding="utf-8")
    assert 'def _read_back' in source and '"GET", url, params=params' in source  # and it can only read


def test_the_todoist_task_is_created_only_by_the_function_that_runs_after_an_approval():
    path = ROOT / "diya_connector_tools.py"
    assert enclosing_functions(path, calls_attr(("httpx", "post"))) == {"search", "todoist_add_task_execute"}  # Notion's search (a read), and the approved task


def test_an_approved_action_is_executed_in_exactly_one_place():
    offenders = []
    for path in project_modules():
        if path.name == "diya_actions.py":
            continue
        if re.search(r"\bkind\.execute\(|\.execute\(\s*(?:self\.)?config\s*,", path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert offenders == []
    assert len(re.findall(r"kind\.execute\(", (ROOT / "diya_actions.py").read_text(encoding="utf-8"))) == 1


def test_running_an_action_needs_it_to_be_approved(tmp_path):
    """The single place that executes refuses anything that was not approved for exactly these arguments."""
    from diya_db import Store
    from fakes import task_kind

    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "a.db"))
    ran = []
    actions = diya_actions.Actions(Store(config.db_path), config, (task_kind(executed=ran),))
    action = actions.propose("add_task", {"title": "x"})
    with pytest.raises(diya_actions.IllegalTransition):
        actions.run(action["id"])  # proposed, never approved
    assert ran == []


# ---- the document is generated from the catalog -----------------------------------------------------------------------------------------------

def test_the_authority_document_is_current():
    current = (ROOT / "docs" / "AUTHORITY_MODEL.md").read_bytes().decode("utf-8")
    assert current == catalog.render(), "run: python diya_catalog.py write"
    assert "Not built (so nothing here can do it)" in current and all(f"`{name}`" in current for name in catalog.CATALOG)
