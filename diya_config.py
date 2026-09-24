"""Runtime configuration for Diya, read from DIYA_* environment variables.

Every default here is the value that used to be hard-coded, so an install with
no DIYA_* variables set behaves exactly as it did before. Relative paths stay
relative to the working directory, as they always were.

`load_config()` only reads the environment (no filesystem access), and it is
called wherever a setting is needed rather than cached at import, so nothing in
this module -- or anything that imports it -- has side effects.
"""
from __future__ import annotations

import glob
import ipaddress
import os
from dataclasses import dataclass


# "staged": Dreaming writes candidate facts to a review queue and never touches the trusted
# profile. "direct": the original behaviour (append straight to the profile), kept only as an
# explicit compatibility option.
DREAM_PROFILE_MODES = ("staged", "direct")


# The names the API always answers to. Anything else is only reachable when the user has both
# switched LAN mode on and said which names other devices will use (see check_exposure()).
LOOPBACK_NAMES = ("localhost", "127.0.0.1", "::1")

# The only hosts get_weather (diya.py) reaches -- what used to be hard-coded there. A positive
# list of external services: nothing local or on the LAN is on it, and nothing gets on it by
# being loopback or a private address (see DIYA_TOOL_ALLOWED_HOSTS).
DEFAULT_TOOL_ALLOWED_HOSTS = ("geocoding-api.open-meteo.com", "api.open-meteo.com")
_TRUE_WORDS = ("1", "true", "yes", "on")
_FALSE_WORDS = ("0", "false", "no", "off")


class ConfigError(ValueError):
    """A DIYA_* environment variable holds a value that can't be used."""


@dataclass(frozen=True)
class Config:
    db_path: str = "diya.db"
    model: str = "qwen2.5:3b"
    embed_model: str = "nomic-embed-text"
    ollama_url: str = "http://localhost:11434/v1"
    notes_dir: str = "sample_notes"
    profile_path: str = "user_profile.txt"
    dream_log_path: str = "dream_log.txt"
    dream_state_path: str = "dream_state.json"
    dream_pending_path: str = "dream_pending.jsonl"
    dream_profile_mode: str = "staged"
    whisper_model: str = "base"
    # The API listens on this computer only. Reaching it from another device (the iPhone) is an
    # explicit choice: DIYA_LAN=1 plus DIYA_ALLOWED_HOSTS (never an accident of the default).
    host: str = "127.0.0.1"
    port: int = 8080
    lan: bool = False
    allowed_hosts: tuple = ()  # extra names the API answers to, beyond loopback (LAN mode)
    frontend_port: int = 3000  # where the Next.js UI is served; only its origins may call the API
    # Requests over this size get a 413 before any route -- or the model -- ever sees them.
    # 1,000,000 bytes is generous for a chat message (or any other JSON payload) and far below
    # what an audio recording needs.
    max_body_bytes: int = 1_000_000
    # /api/transcribe gets its own, larger allowance: audio uploads are legitimately much bigger
    # than a chat message. 25,000,000 bytes is a few minutes of compressed audio at typical bitrates.
    max_transcribe_bytes: int = 25_000_000
    ssl_certfile: str | None = None
    ssl_keyfile: str | None = None
    # Folders `list_files` may look inside, beyond the default folder (see default_files_root());
    # DIYA_FILES_ROOTS. Empty means "the default folder only" -- never the repo root, never the
    # home directory at large.
    files_roots: tuple = ()
    # Hosts the agent's own network tools may reach (checked in diya._fetch, before any request is
    # sent); DIYA_TOOL_ALLOWED_HOSTS. Setting it replaces the default rather than adding to it.
    tool_allowed_hosts: tuple = DEFAULT_TOOL_ALLOWED_HOSTS


def _parse_host_list(setting: str, raw: str) -> tuple:
    """A comma-separated list of plain host names or IPv4 addresses, as DIYA_ALLOWED_HOSTS and
    DIYA_TOOL_ALLOWED_HOSTS both take: lowercased, blanks skipped, duplicates dropped, order kept.
    One parser for both, so the two settings can't quietly drift apart."""
    names = []
    for item in raw.split(","):
        name = item.strip().lower()
        if not name:
            continue
        if name == "0.0.0.0" or any(ch in name for ch in "*/:@?# \t"):
            raise ConfigError(
                f"{setting} entries must be plain host names or IPv4 addresses "
                f"(no scheme, port, path or wildcard), got {item.strip()!r}"
            )
        names.append(name)
    return tuple(dict.fromkeys(names))


_STRING_SETTINGS = {
    "db_path": "DIYA_DB_PATH",
    "model": "DIYA_MODEL",
    "embed_model": "DIYA_EMBED_MODEL",
    "ollama_url": "DIYA_OLLAMA_URL",
    "notes_dir": "DIYA_NOTES_DIR",
    "profile_path": "DIYA_PROFILE_PATH",
    "dream_log_path": "DIYA_DREAM_LOG_PATH",
    "dream_state_path": "DIYA_DREAM_STATE_PATH",
    "dream_pending_path": "DIYA_DREAM_PENDING_PATH",
    "whisper_model": "DIYA_WHISPER_MODEL",
    "host": "DIYA_HOST",
}


def load_config(env=None) -> Config:
    """Build a Config from `env` (defaults to os.environ). Blank values count as unset."""
    env = os.environ if env is None else env

    def read(name):
        value = env.get(name)
        return None if value is None or not value.strip() else value.strip()

    values = {}
    for field, name in _STRING_SETTINGS.items():
        value = read(name)
        if value is not None:
            values[field] = value

    port = read("DIYA_PORT")
    if port is not None:
        try:
            values["port"] = int(port)
        except ValueError:
            raise ConfigError(f"DIYA_PORT must be an integer, got {port!r}") from None
        if not 1 <= values["port"] <= 65535:
            raise ConfigError(f"DIYA_PORT must be between 1 and 65535, got {values['port']}")

    lan = read("DIYA_LAN")
    if lan is not None:
        if lan.lower() in _TRUE_WORDS:
            values["lan"] = True
        elif lan.lower() not in _FALSE_WORDS:
            raise ConfigError(f"DIYA_LAN must be one of {', '.join(_TRUE_WORDS + _FALSE_WORDS)}, got {lan!r}")
    if values.get("lan") and "host" not in values:
        values["host"] = "0.0.0.0"  # LAN mode with no explicit interface: listen on all of them

    hosts = read("DIYA_ALLOWED_HOSTS")
    if hosts is not None:
        values["allowed_hosts"] = _parse_host_list("DIYA_ALLOWED_HOSTS", hosts)

    tool_hosts = read("DIYA_TOOL_ALLOWED_HOSTS")
    if tool_hosts is not None:
        values["tool_allowed_hosts"] = _parse_host_list("DIYA_TOOL_ALLOWED_HOSTS", tool_hosts)

    files_roots = read("DIYA_FILES_ROOTS")
    if files_roots is not None:
        # Comma-list, same shape as DIYA_ALLOWED_HOSTS above -- but a file path, unlike a host
        # name, is legitimately case-sensitive and legitimately contains ":", "\\", "/" and
        # spaces, so it is stripped and deduplicated only, never lowercased or character-checked.
        paths = [item.strip() for item in files_roots.split(",")]
        values["files_roots"] = tuple(dict.fromkeys(p for p in paths if p))

    frontend_port = read("DIYA_FRONTEND_PORT")
    if frontend_port is not None:
        try:
            values["frontend_port"] = int(frontend_port)
        except ValueError:
            raise ConfigError(f"DIYA_FRONTEND_PORT must be an integer, got {frontend_port!r}") from None
        if not 1 <= values["frontend_port"] <= 65535:
            raise ConfigError(f"DIYA_FRONTEND_PORT must be between 1 and 65535, got {values['frontend_port']}")

    max_body = read("DIYA_MAX_BODY_BYTES")
    if max_body is not None:
        try:
            values["max_body_bytes"] = int(max_body)
        except ValueError:
            raise ConfigError(f"DIYA_MAX_BODY_BYTES must be an integer, got {max_body!r}") from None
        if values["max_body_bytes"] < 1:
            raise ConfigError(f"DIYA_MAX_BODY_BYTES must be at least 1, got {values['max_body_bytes']}")

    max_transcribe = read("DIYA_MAX_TRANSCRIBE_BYTES")
    if max_transcribe is not None:
        try:
            values["max_transcribe_bytes"] = int(max_transcribe)
        except ValueError:
            raise ConfigError(
                f"DIYA_MAX_TRANSCRIBE_BYTES must be an integer, got {max_transcribe!r}"
            ) from None
        if values["max_transcribe_bytes"] < 1:
            raise ConfigError(
                f"DIYA_MAX_TRANSCRIBE_BYTES must be at least 1, got {values['max_transcribe_bytes']}"
            )

    mode = read("DIYA_DREAM_PROFILE_MODE")
    if mode is not None:
        if mode.lower() not in DREAM_PROFILE_MODES:
            raise ConfigError(
                f"DIYA_DREAM_PROFILE_MODE must be one of {', '.join(DREAM_PROFILE_MODES)}, got {mode!r}"
            )
        values["dream_profile_mode"] = mode.lower()

    cert, key = read("DIYA_SSL_CERT"), read("DIYA_SSL_KEY")
    if (cert is None) != (key is None):
        raise ConfigError("DIYA_SSL_CERT and DIYA_SSL_KEY must be set together")
    if cert is not None:
        values["ssl_certfile"], values["ssl_keyfile"] = cert, key

    return Config(**values)


def is_loopback(host: str) -> bool:
    """True for an address that only this computer can reach."""
    host = host.strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:  # a name that isn't an address ("127.evil.example") is not vouched for
        return False


def api_allowed_hosts(config: Config) -> tuple[str, ...]:
    """The Host names the API answers to: loopback always, plus whatever LAN mode was told."""
    extra = [h for h in config.allowed_hosts if h not in LOOPBACK_NAMES]
    return tuple(LOOPBACK_NAMES) + tuple(extra)


def api_allowed_origins(config: Config) -> tuple[str, ...]:
    """The browser origins allowed to call the API: the UI's own address, on each allowed name.
    Derived from the allowed hosts, so no address or origin is written into the code."""
    return tuple(
        f"https://{'[' + h + ']' if ':' in h else h}:{config.frontend_port}"
        for h in api_allowed_hosts(config)
    )


def default_files_root() -> str:
    """Where `list_files` may look when DIYA_FILES_ROOTS hasn't been set: a dedicated folder, not
    the repo root and not the home directory at large, so a fresh install starts able to see
    nothing sensitive by default."""
    return os.path.join(os.path.expanduser("~"), "Documents", "Diya")


def resolved_files_roots(config: Config) -> tuple[str, ...]:
    """The folders `list_files` may look inside: whatever DIYA_FILES_ROOTS configured, or the one
    dedicated default folder if nothing was configured. Configuring DIYA_FILES_ROOTS replaces the
    default rather than adding to it -- the same way every other path setting in this module
    (DIYA_DB_PATH, DIYA_NOTES_DIR, ...) is a full replacement, not an addition -- so a user who
    wants the default folder alongside something else lists both explicitly."""
    return config.files_roots or (default_files_root(),)


def check_exposure(config: Config) -> None:
    """Refuse to start with a configuration that would expose the API by accident."""
    if not is_loopback(config.host) and not config.lan:
        raise ConfigError(
            f"DIYA_HOST={config.host} would make the API reachable from other devices. "
            "The API listens on this computer only unless you turn on LAN mode deliberately: "
            "set DIYA_LAN=1 and DIYA_ALLOWED_HOSTS"
        )
    if config.lan and not config.allowed_hosts:
        raise ConfigError(
            "DIYA_LAN=1 needs DIYA_ALLOWED_HOSTS: the name or address the other device uses to reach "
            "this computer (comma-separated). Without it nothing but this computer could connect"
        )


def tls_files(config: Config, search_dir: str = ".") -> tuple[str, str] | None:
    """The (certfile, keyfile) to serve with, or None if there isn't one.

    Uses DIYA_SSL_CERT/KEY when set. Otherwise looks for a single mkcert pair in
    `search_dir` (mkcert names them `<name>+N.pem` and `<name>+N-key.pem`), so no
    LAN address needs to be written into the code. More than one pair is an error
    rather than a guess.
    """
    if config.ssl_certfile and config.ssl_keyfile:
        for path in (config.ssl_certfile, config.ssl_keyfile):
            if not os.path.isfile(path):
                raise ConfigError(f"TLS file not found: {path}")
        return config.ssl_certfile, config.ssl_keyfile

    pairs = []
    for key in sorted(glob.glob(os.path.join(search_dir, "*+*-key.pem"))):
        cert = key[: -len("-key.pem")] + ".pem"
        if os.path.isfile(cert):
            pairs.append((cert, key))
    if len(pairs) > 1:
        names = ", ".join(os.path.basename(cert) for cert, _ in pairs)
        raise ConfigError(
            f"More than one mkcert certificate found ({names}); "
            "set DIYA_SSL_CERT and DIYA_SSL_KEY to choose one"
        )
    return pairs[0] if pairs else None
