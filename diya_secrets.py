"""Secrets at rest: a connector's sign-in and Google's client secret are stored encrypted for the Windows user who made them (docs/SECRETS_DESIGN.md), added 2026-10-18.

Before this, a refresh token sat in a plain file in the connector tokens folder, and that folder is beside the code by default, which for this project is inside OneDrive: a copy of every sign-in was
being uploaded. On Windows the files now hold the token protected with DPAPI (the operating system's own per-user encryption, `CryptProtectData`): only the same Windows user on the same machine can
turn it back into the token, so a copy in the cloud, in a backup or in a stolen folder is useless without that login. A file written before this (plain text) is still read, and is rewritten protected
the first time it is read. Elsewhere (no DPAPI) nothing is changed: the file stays as it was, and the design doc says so.

What this is not: it does not protect against something running as the same Windows user on the unlocked machine (that program can ask DPAPI too; the extra "entropy" below only stops a program that does
not know it from decrypting by accident), and it is not a password: nothing is asked of the owner. DIYA_PROTECT_SECRETS=0 switches it off.

Importing this module has no side effects.
"""
from __future__ import annotations

import base64
import binascii
import sys

PREFIX = "dpapi1:"
_ENTROPY = b"diya-connector-secrets-v1"
_UI_FORBIDDEN = 0x1  # CRYPTPROTECT_UI_FORBIDDEN: never put up a window


def available():
    """Can this machine protect a secret for the current user? (Windows: DPAPI.)"""
    return sys.platform == "win32"


def _windows_crypt(function, data):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob_of(raw):
        buffer = ctypes.create_string_buffer(raw, len(raw))
        return Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    source, keep_source = blob_of(data)
    entropy, keep_entropy = blob_of(_ENTROPY)
    out = Blob()
    if function == "protect":
        ok = crypt32.CryptProtectData(ctypes.byref(source), None, ctypes.byref(entropy), None, None, _UI_FORBIDDEN, ctypes.byref(out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(entropy), None, None, _UI_FORBIDDEN, ctypes.byref(out))
    del keep_source, keep_entropy
    if not ok:
        raise OSError(f"Windows could not {function} the secret (error {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


class Backend:
    """What turns bytes into protected bytes and back. A test can hand in another (a reversible stand-in) so that its answer does not depend on the machine it runs on."""

    def protect(self, data):
        return _windows_crypt("protect", data)

    def unprotect(self, data):
        return _windows_crypt("unprotect", data)


_backend = Backend()


def protect(text, enabled=True):
    """`text` as it is stored: protected for this Windows user and marked so, or unchanged when protection is off or this machine cannot do it. Never raises for a machine that cannot: the secret is
    stored as before, which is the safe direction for a feature that must not lose a sign-in."""
    if not enabled or not available():
        return text
    try:
        return PREFIX + base64.b64encode(_backend.protect(text.encode("utf-8"))).decode("ascii")
    except OSError:
        return text


def is_protected(stored):
    return isinstance(stored, str) and stored.startswith(PREFIX)


def unprotect(stored):
    """The secret behind what was stored: the text itself for a plain (older or unprotected) value, the decrypted text for a protected one, or None for one that cannot be decrypted here (copied from
    another Windows user or machine, or damaged): the caller treats that as "not connected", never as an error that stops Diya."""
    if not isinstance(stored, str):
        return None
    if not is_protected(stored):
        return stored
    if not available():
        return None
    try:
        return _backend.unprotect(base64.b64decode(stored[len(PREFIX):], validate=True)).decode("utf-8")
    except (OSError, ValueError, binascii.Error):
        return None
