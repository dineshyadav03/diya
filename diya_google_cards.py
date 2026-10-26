"""The newer Google cards: one place that makes them (docs/GOOGLE_CHANGES.md), added 2026-10-26.

Each capability beyond the first five is its OWN card on the Connections page with its own narrow Google permission, off until the owner adds that permission in their Google project, switches the API on and presses
Connect. This module builds the Connector for a card from a few facts (name, label, the one permission, the APIs to switch on, what it can and cannot do) and remembers its name, so that disconnecting the last
Google card takes the permission back at Google (diya_google_calendar.revoke_for) and forgetting Google's app disconnects every card. "Connect all Google" does not include these: it connects the first five only.

Importing this module has no side effects.
"""
from __future__ import annotations

import webbrowser

import diya_connectors
import diya_google_calendar

CARDS = {}  # name -> (label, scope)
MODULES = ("diya_google_mailwrite", "diya_google_calchange", "diya_google_drive", "diya_google_contacts")  # the modules that make cards; a new one is named here so that disconnecting and forgetting Google know of its cards


def names():
    """The name of every newer Google card, found by making the cards of each module once (a card is remembered when it is made)."""
    import importlib

    for module in MODULES:
        importlib.import_module(module).connectors()
    return tuple(CARDS)


def _steps(apis, scope):
    return (
        "Use the same Google Cloud project as for Calendar (console.cloud.google.com).",
        f"APIs & Services, Library: search for {apis} and press Enable (each one).",
        f"OAuth consent screen (Google Auth platform), Data access: add the scope {scope}. Your own address is already a test user; keep Publishing status on In production.",
        "The Client ID and secret are shared with the other Google cards: if you pasted them for those, just press Connect.",
    )


def card(name, label, description, scope, apis, access):
    """The Connector for a new Google card, and its name remembered. `access` is what it can and cannot do, one plain sentence each (it must say that a change waits for approval and what it cannot do)."""
    CARDS[name] = (label, scope)

    def connect(config, open_browser=None):
        return diya_google_calendar.connect_to(config, scope, name, open_browser or webbrowser.open)

    setup = diya_connectors.Setup(fields=diya_google_calendar.SETUP.fields, steps=_steps(apis, scope), state=diya_google_calendar.client_state, save=diya_google_calendar.save_client, clear=diya_google_calendar.clear_client)
    return diya_connectors.Connector(name=name, label=label, description=description, auth_kind="oauth", implemented=True, oauth_connect=connect, setup=setup, revoke=diya_google_calendar.revoke_for(name), scope=scope, access=tuple(access))
