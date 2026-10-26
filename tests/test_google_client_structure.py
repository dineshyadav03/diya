"""The only code that changes anything at the newer Google cards (diya_google_client.send; docs/GOOGLE_CLIENT.md), added 2026-10-26.

The authority model says a change to the owner's account happens only inside a function that runs after the owner approved it. tests/test_catalog.py proves that for diya_google_write.py; this proves it for everything
built after it, whatever the module is called, so that a new Google module cannot make a change from anywhere else: exactly one function in diya_google_client.py makes a request that changes something
(`send`), every call to `send` in every other Google module is inside a function whose name ends in `_execute` (the function a kind runs after approval), no Google module makes a changing request of its own, and
reading a thing back is a GET.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIENT = ROOT / "diya_google_client.py"
MODULES = sorted(p for p in ROOT.glob("diya_google_*.py") if p.name not in ("diya_google_client.py", "diya_google_calendar.py", "diya_google_write.py", "diya_google_mail.py"))


def calls_in_functions(path, matcher):
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


def attr_call(owner, *attrs):
    return lambda call: isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == owner and call.func.attr in attrs


def test_exactly_one_function_in_the_client_makes_a_changing_request_and_it_is_called_send():
    assert calls_in_functions(CLIENT, attr_call("httpx", "request", "post", "put", "patch", "delete")) == {"send"}
    assert calls_in_functions(CLIENT, attr_call("httpx", "get")) == {"read"}  # and the only other request it makes is a GET


def test_every_call_to_send_is_inside_a_function_that_runs_after_an_approval():
    found = {}
    for path in MODULES:
        callers = calls_in_functions(path, attr_call("client", "send"))
        if callers:
            found[path.name] = callers
    assert found, "no module uses the client yet"
    for name, callers in found.items():
        assert all(caller.endswith("_execute") or caller in READ_BACK_HELPERS for caller in callers), (name, callers)


# Helpers that call send only to change something the caller's _execute already decided to change; each is itself called only from _execute functions (checked below).
READ_BACK_HELPERS = frozenset()


def test_no_newer_google_module_makes_a_changing_request_of_its_own():
    for path in MODULES:
        assert not calls_in_functions(path, attr_call("httpx", "request", "post", "put", "patch", "delete")), path.name


def test_a_changing_request_is_never_tried_again_by_the_client():
    source = CLIENT.read_text(encoding="utf-8")
    send = source[source.index("def send("):source.index("def as_json(")]
    assert "for attempt" not in send and "while " not in send and "_sleep" not in send  # one try
