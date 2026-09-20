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
import os
from dataclasses import dataclass


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
    whisper_model: str = "base"
    host: str = "0.0.0.0"
    port: int = 8080
    ssl_certfile: str | None = None
    ssl_keyfile: str | None = None


_STRING_SETTINGS = {
    "db_path": "DIYA_DB_PATH",
    "model": "DIYA_MODEL",
    "embed_model": "DIYA_EMBED_MODEL",
    "ollama_url": "DIYA_OLLAMA_URL",
    "notes_dir": "DIYA_NOTES_DIR",
    "profile_path": "DIYA_PROFILE_PATH",
    "dream_log_path": "DIYA_DREAM_LOG_PATH",
    "dream_state_path": "DIYA_DREAM_STATE_PATH",
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

    cert, key = read("DIYA_SSL_CERT"), read("DIYA_SSL_KEY")
    if (cert is None) != (key is None):
        raise ConfigError("DIYA_SSL_CERT and DIYA_SSL_KEY must be set together")
    if cert is not None:
        values["ssl_certfile"], values["ssl_keyfile"] = cert, key

    return Config(**values)


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
