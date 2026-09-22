#!/usr/bin/env python3
"""CI hygiene check: no private-range IPv4 address (10.x, 172.x, 192.x) is hardcoded into any
tracked file outside tests/.

Diya's own network settings are read from DIYA_* environment variables and a discovered
certificate -- never a literal address in the code (see diya_config.py's
is_loopback/api_allowed_hosts/tls_files) -- and the docs use placeholders such as <name-or-ip>.
`tests/` is excluded because its fixtures deliberately use private-range-shaped placeholder values
(see LAN_ENV in tests/test_boundary.py) to exercise the Host/Origin allowlist; those are correct,
not a leak. This file's own docstring used to name one of those placeholders directly, which
tripped this very check once it also covered scripts/ -- described instead of quoted, from here on.

This is the same regex tests/test_config.py's test_module_source_contains_no_hardcoded_lan_address
already checks inside diya_config.py alone, applied here at repo scope instead of one file.

Run directly (`python scripts/check_hardcoded_addresses.py`) or as a CI step. Exits 1 and prints
every match if it finds one; tests/test_hardcoded_address_scan.py exercises the same logic so a
regression is also caught by the ordinary local test run, not only in CI.
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BINARY_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2", ".zip"}
EXCLUDED_PREFIXES = ("tests/",)
ADDRESS = re.compile(r"\b(10|172|192)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def tracked_files(root=ROOT):
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True
    )
    return result.stdout.splitlines()


def find_problems(root=ROOT):
    """Every "path:line: address" hit outside tests/, in tracked, non-binary text files."""
    problems = []
    for name in tracked_files(root):
        if name.startswith(EXCLUDED_PREFIXES):
            continue
        path = root / name
        if path.suffix.lower() in BINARY_EXT or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # not our concern here -- test_text_files.py enforces encoding separately
        for match in ADDRESS.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            problems.append(f"{name}:{line}: {match.group(0)}")
    return problems


def main():
    problems = find_problems()
    if problems:
        print("Hardcoded private-network address found outside tests/:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("No hardcoded private-network addresses found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
