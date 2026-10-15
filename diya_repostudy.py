"""Studying a public GitHub repository, with the evidence shown (docs/REPO_STUDY_DESIGN.md).

Asked to study or explain a repository ("study https://github.com/owner/repo", "how does this work"), Diya reads it the way a careful reviewer would: from the outside, read-only, and keeps three
kinds of statement apart. This is the method of REA ("Reverse Engineer Anything", https://github.com/morluto/rea, MIT licence) put to Diya's scale: its rule that a report separates what was
OBSERVED (read from a named file or from GitHub), what was INFERRED (a guess from names and shapes, with its basis), and what is NOT ESTABLISHED (what was not looked at, so that a missing
fact is never taken for proof that something is absent). No code of REA is used here; nothing of the repository is run, installed or saved to disk.

Code does the reading and builds the report from the facts (study, render). The model, in a second answer that is given no tools, is asked only to explain in a few plain sentences what the
evidence shows (explain_note): a README is text anyone can write, so it is read, never obeyed.

Everything reaches GitHub through `fetch(url) -> (status, text)`, which the caller supplies (diya.py supplies the allowlisted one: only api.github.com and raw.githubusercontent.com, GET, no
redirects followed, no credentials sent), so the whole of this module is tested without a network.
"""
from __future__ import annotations

import json
import re
import tomllib
from urllib.parse import quote

GITHUB_HOSTS = ("api.github.com", "raw.githubusercontent.com")
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
MAX_REQUESTS = 16  # per study: two to GitHub's API, the rest are files
MAX_FILES_READ = 10
MAX_README_CHARS = 6000
MAX_FILE_CHARS = 5000
MAX_MANIFEST_CHARS = 60000  # a manifest is parsed, not read aloud, and is useless cut in half
MAX_FACT_CHARS = 400

_URL = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100})(?=$|[/?#\s)>\]\"',;]|\.(?:\s|$))", re.IGNORECASE)
_STUDY_WORDS = re.compile(
    r"\b(?:study|studi(?:ed|es)|analy[sz]e|analysis|reverse[- ]engineer\w*|understand|explain|break\s+(?:it\s+)?down|how\s+(?:does|do|did|is|it|this)\b|what\s+(?:is|does|are)|overview|architecture|"
    r"review|look\s+(?:at|into)|go\s+through|read|summari[sz]e|tell\s+me\s+about|walk\s+me\s+through)\b",
    re.IGNORECASE,
)


class StudyError(RuntimeError):
    """The repository could not be read; the words are safe to show the person."""


def repo_from_text(text):
    """(owner, repo) of the first GitHub repository address in `text`, or None. A bare "owner/name" is not taken for one: only an address is."""
    if not isinstance(text, str):
        return None
    found = _URL.search(text)
    if not found:
        return None
    owner, repo = found.group(1), found.group(2)
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if owner in (".", "..") or repo in (".", "..", "") or owner.startswith(".") and len(owner) < 2:
        return None
    return owner, repo


def wants_study(text):
    """True if the message gives a repository address and asks for it to be studied, explained or looked into (and is a short, single message, not a pasted page)."""
    if not isinstance(text, str) or len(text) > 600 or "\n" in text.strip():
        return False
    return repo_from_text(text) is not None and _STUDY_WORDS.search(_URL.sub(" ", text)) is not None  # the words are looked for outside the address itself


# ---- reading ----------------------------------------------------------------------------------------------------------------------

class _Reader:
    """Every request goes through here: counted, bounded, and a failure says what it was."""

    def __init__(self, fetch):
        self.fetch, self.requests = fetch, 0

    def get(self, url):
        if self.requests >= MAX_REQUESTS:
            raise StudyError("That repository needed more requests than one study is allowed to make.")
        self.requests += 1
        try:
            status, body = self.fetch(url)
        except StudyError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a refused host, a timeout, no connection
            raise StudyError(f"I could not reach GitHub ({type(exc).__name__}).") from exc
        return status, body

    def json(self, url, what):
        status, body = self.get(url)
        if status == 404:
            raise StudyError(f"There is no public repository there ({what}). It may be private, renamed or spelled differently.")
        if status in (403, 429):
            raise StudyError("GitHub's limit on unsigned requests was reached. Try again in a while.")
        if status in (301, 302, 307, 308):
            raise StudyError("That repository has moved; use its new address.")
        if status != 200:
            raise StudyError(f"GitHub answered with an error (HTTP {status}).")
        try:
            return json.loads(body)
        except ValueError as exc:
            raise StudyError("GitHub sent back something I could not read.") from exc

    def text(self, owner, repo, branch, path, limit):
        """A file's start, or None if it is not there. Reading a file is never fatal."""
        try:
            status, body = self.get(f"{RAW}/{owner}/{repo}/{quote(branch, safe='')}/{quote(path)}")
        except StudyError:
            return None
        if status != 200 or not isinstance(body, str):
            return None
        return body[:limit]


def _clean(text, limit=MAX_FACT_CHARS):
    """One line, with every control and invisible character made visible: this text came from a stranger."""
    import diya_memory

    return diya_memory.printable(text, limit)


def _fact(kind, text, source):
    return {"kind": kind, "text": _clean(text), "source": _clean(source, 120)}


# What a folder is usually for, by its name. A guess, and reported as one.
_FOLDER_PURPOSE = {
    "src": "source code", "lib": "library code", "app": "application code", "apps": "applications", "packages": "separate packages", "pkg": "packages", "cmd": "command-line entry points",
    "internal": "private implementation", "docs": "documentation", "doc": "documentation", "examples": "examples", "example": "examples", "test": "tests", "tests": "tests", "spec": "tests",
    "scripts": "helper scripts", "bin": "executables", "tools": "tooling", "bridge": "adapters to other programs", "skills": "agent skills", "plugins": "plugins", "public": "static files",
    "assets": "static files", "config": "configuration", "docker": "container setup", "migrations": "database changes", ".github": "GitHub automation (workflows, templates)",
}
# folders that hold several projects side by side: what is inside them is worth one more line
_CONTAINERS = {"apps", "packages", "services", "cmd", "crates", "modules", "plugins", "src", "lib"}
_MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "Gemfile", "composer.json", "Dockerfile", "Makefile", "CMakeLists.txt")
_DOCS = ("ARCHITECTURE.md", "CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md")
_ENTRY_NAMES = re.compile(r"^(?:main|index|app|cli|server|manage|run|__main__)\.(?:py|js|mjs|ts|tsx|go|rs|java|rb|php)$", re.IGNORECASE)
_LANGUAGE = {
    ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java",
    ".kt": "Kotlin", ".swift": "Swift", ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".sh": "Shell", ".ps1": "PowerShell",
    ".md": "Markdown", ".mdx": "MDX", ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".json": "JSON", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".sql": "SQL", ".java": "Java",
}
_IGNORED_LANGUAGES = {"JSON", "YAML", "TOML", "Markdown", "MDX"}  # data and prose, shown on their own line, not as "the language of the project"


def _extension(path):
    name = path.rsplit("/", 1)[-1]
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name.strip(".") else ""


def _tree_facts(files, truncated):
    """The facts that can be had from the list of files alone: how big, what languages, what the top folders look like, what files suggest an entry point."""
    facts = []
    facts.append(_fact("observed", f"{len(files)} files in the tree" + (" (GitHub cut the list short, so the real number is larger)" if truncated else ""), "file tree"))
    counts, sizes = {}, {}
    for path, size in files:
        language = _LANGUAGE.get(_extension(path))
        if language:
            counts[language] = counts.get(language, 0) + 1
            sizes[language] = sizes.get(language, 0) + int(size or 0)
    code = {name: sizes[name] for name in counts if name not in _IGNORED_LANGUAGES}
    if code:
        total = sum(code.values()) or 1
        top = sorted(code, key=code.get, reverse=True)[:5]
        facts.append(_fact("observed", "code by file size: " + ", ".join(f"{name} {100 * code[name] // total}%" for name in top), "file tree (the extension of each file name)"))
    prose = [f"{name} {counts[name]} files" for name in ("Markdown", "MDX") if counts.get(name)]
    if prose:
        facts.append(_fact("observed", "documents: " + ", ".join(prose), "file tree"))
    tops = {}
    for path, _ in files:
        top = path.split("/", 1)[0] if "/" in path else None
        if top:
            tops[top] = tops.get(top, 0) + 1
    for name in sorted(tops, key=tops.get, reverse=True)[:8]:
        purpose = _FOLDER_PURPOSE.get(name.lower())
        facts.append(_fact("observed", f"folder {name}/ holds {tops[name]} files", "file tree"))
        if purpose:
            facts.append(_fact("inferred", f"{name}/ is probably {purpose}", f"the folder's name; its contents were not read"))
    for container in sorted(tops, key=tops.get, reverse=True):
        if container.lower() not in _CONTAINERS:
            continue
        inner = {}
        for path, _ in files:
            parts = path.split("/")
            if parts[0] == container and len(parts) > 2:
                inner[parts[1]] = inner.get(parts[1], 0) + 1
        if inner:
            listed = sorted(inner, key=inner.get, reverse=True)[:8]
            facts.append(_fact("observed", f"inside {container}/: " + ", ".join(f"{name} ({inner[name]} files)" for name in listed), "file tree"))
    entries = [path for path, _ in files if _ENTRY_NAMES.match(path.rsplit("/", 1)[-1]) and path.count("/") <= 2]
    if entries:
        facts.append(_fact("observed", "files named like an entry point: " + ", ".join(sorted(entries)[:6]), "file tree"))
    for manifest in _MANIFESTS:
        if any(path == manifest for path, _ in files):
            facts.append(_fact("observed", f"{manifest} is at the top", "file tree"))
    return facts


def _short_list(items, limit=8):
    items = [str(i) for i in items]
    return ", ".join(items[:limit]) + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _manifest_facts(path, text):
    """What a manifest declares, as facts. A file that does not parse gives one fact saying so."""
    facts = []
    try:
        if path.endswith("package.json"):
            data = json.loads(text)
            if data.get("name"):
                facts.append(_fact("observed", f"package name: {data['name']}", path))
            scripts = data.get("scripts") or {}
            if scripts:
                facts.append(_fact("observed", "scripts: " + _short_list([f"{k} = {str(v)[:60]}" for k, v in scripts.items()], 6), path))
            for key in ("dependencies", "devDependencies"):
                if data.get(key):
                    facts.append(_fact("observed", f"{key}: " + _short_list(sorted(data[key]), 10), path))
            if data.get("main") or data.get("bin"):
                facts.append(_fact("observed", f"declares an entry: main={data.get('main')} bin={data.get('bin')}", path))
            if data.get("workspaces"):
                facts.append(_fact("observed", f"is a workspace root: {data['workspaces']}", path))
        elif path.endswith("pyproject.toml"):
            data = tomllib.loads(text)
            project = data.get("project") or {}
            if project.get("name"):
                facts.append(_fact("observed", f"python project: {project['name']} {project.get('version', '')}".strip(), path))
            if project.get("dependencies"):
                facts.append(_fact("observed", "dependencies: " + _short_list([re.split(r"[<>=!~; \[]", d)[0] for d in project["dependencies"]], 10), path))
            if project.get("scripts"):
                facts.append(_fact("observed", "command-line scripts: " + _short_list(project["scripts"]), path))
        elif path.endswith("Cargo.toml"):
            data = tomllib.loads(text)
            if data.get("package", {}).get("name"):
                facts.append(_fact("observed", f"rust crate: {data['package']['name']}", path))
            if data.get("dependencies"):
                facts.append(_fact("observed", "dependencies: " + _short_list(sorted(data["dependencies"]), 10), path))
        elif path.endswith("requirements.txt"):
            names = [re.split(r"[<>=!~; \[]", line.strip())[0] for line in text.splitlines() if line.strip() and not line.strip().startswith(("#", "-"))]
            facts.append(_fact("observed", "requirements: " + _short_list(names, 12), path))
        elif path.endswith("go.mod"):
            module = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
            needs = re.findall(r"^\s*(?:require\s+)?([\w./-]+\.[\w./-]+)\s+v[\w.+-]+", text, re.MULTILINE)
            if module:
                facts.append(_fact("observed", f"go module: {module.group(1)}", path))
            if needs:
                facts.append(_fact("observed", "requires: " + _short_list(needs, 8), path))
    except (ValueError, tomllib.TOMLDecodeError, AttributeError, TypeError):
        facts.append(_fact("observed", f"{path} is there but I could not parse it", path))
    return facts


_LINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
_HTML = re.compile(r"<[^>]*>")


def _prose(line):
    """What is left of a line when links, images and html tags are taken out."""
    return " ".join(_HTML.sub(" ", _LINK.sub(" ", line)).replace("*", " ").replace("`", " ").split()).strip(" ·|-_")


def _first_paragraph(text):
    """The first paragraph of real prose in a README: headings, badges, rows of links, images, tables and html are skipped (a line counts only if forty characters of prose are left once the
    links and tags are taken out). It runs on over the following lines until a blank line, up to about 500 characters."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if lines and not line:
            break
        if not lines:
            if not line or line.startswith(("#", "|", "---", "```", ">")) or len(_prose(line)) < 40:
                continue
        lines.append(_LINK.sub(lambda m: re.sub(r"^!?\[|\]\([^)]*\)$", "", m.group(0)), line))
        if sum(len(x) for x in lines) > 500:
            break
    return " ".join(lines)


def study(fetch, owner, repo):
    """Read a repository from the outside and return the evidence: {repo, url, branch, facts: [{kind, text, source}], files_read, limits, requests, readme}. Raises StudyError (safe words) when
    it cannot be read at all. A single file that cannot be read is skipped, and said so in `limits`."""
    reader = _Reader(fetch)
    info = reader.json(f"{API}/repos/{quote(owner)}/{quote(repo)}", f"{owner}/{repo}")
    if not isinstance(info, dict) or not info.get("default_branch"):
        raise StudyError("GitHub did not describe that repository.")
    branch = str(info["default_branch"])
    facts = []
    if info.get("description"):
        facts.append(_fact("observed", f"described as: {info['description']}", "GitHub API"))
    license_name = (info.get("license") or {}).get("spdx_id") or (info.get("license") or {}).get("name")
    facts.append(_fact("observed", f"licence: {license_name or 'none declared'}", "GitHub API"))
    facts.append(_fact("observed", f"{info.get('stargazers_count', 0)} stars; last pushed {str(info.get('pushed_at', '?'))[:10]}; main branch {branch}" + ("; archived" if info.get("archived") else "") + ("; a fork" if info.get("fork") else ""), "GitHub API"))

    tree = reader.json(f"{API}/repos/{quote(owner)}/{quote(repo)}/git/trees/{quote(branch, safe='')}?recursive=1", "its file tree")
    files = [(entry["path"], entry.get("size", 0)) for entry in tree.get("tree", []) if entry.get("type") == "blob" and isinstance(entry.get("path"), str)]
    truncated = bool(tree.get("truncated"))
    facts += _tree_facts(files, truncated)

    present = {path for path, _ in files}
    readme = next((path for path in sorted(present) if "/" not in path and re.fullmatch(r"readme(?:\.\w+)?", path, re.IGNORECASE)), None)
    wanted = ([readme] if readme else []) + [m for m in _MANIFESTS[:7] if m in present] + [d for d in _DOCS if d in present]
    wanted += [p for p in sorted(present) if re.fullmatch(r"docs/architecture[\w-]*\.(?:md|mdx)", p, re.IGNORECASE)][:1]
    read, skipped, readme_text = [], [], ""
    for path in wanted[:MAX_FILES_READ]:
        text = reader.text(owner, repo, branch, path, MAX_README_CHARS if path == readme else MAX_MANIFEST_CHARS if path in _MANIFESTS else MAX_FILE_CHARS)
        if text is None:
            skipped.append(path)
            continue
        read.append(path)
        if path == readme:
            readme_text = text
            paragraph = _first_paragraph(text)
            if paragraph:
                facts.append(_fact("observed", f"the README begins: {paragraph}", path))
        elif path in _MANIFESTS:
            facts += _manifest_facts(path, text)
        else:
            paragraph = _first_paragraph(text)
            if paragraph:
                facts.append(_fact("observed", f"{path} begins: {paragraph}", path))

    limits = [
        "No code of this repository was run, installed or saved: everything here was read through GitHub's public interface.",
        f"{len(read)} of {len(files)} files were read ({_short_list(read, 10) or 'none'}); the rest, including all the code, were not, so what the code really does is not established.",
        "Language shares come from file names and sizes, not from reading the code. Dependencies are what the manifests declare, not proof of what the code uses.",
        "A folder's purpose is a guess from its name unless a document says otherwise.",
    ]
    if skipped:
        limits.append("Not read (missing, or past the limit on requests): " + _short_list(skipped, 6) + ".")
    if truncated:
        limits.append("GitHub cut the file list short, so some files are not counted.")
    if not readme:
        limits.append("There is no README at the top, so what the project is for is not established.")
    return {
        "repo": f"{owner}/{repo}", "url": f"https://github.com/{owner}/{repo}", "branch": branch, "facts": facts, "files_read": read, "limits": limits,
        "requests": reader.requests, "readme": _clean(readme_text, MAX_README_CHARS) if readme_text else "",
    }


# ---- showing it -------------------------------------------------------------------------------------------------------------------

def render(evidence):
    """The report, built by code from the facts: what was observed (with where it was read), what was inferred (with why), and what is not established."""
    out = [f"Repository study: {evidence['repo']} ({evidence['url']})", ""]
    for kind, title in (("observed", "Observed (read from the named place)"), ("inferred", "Inferred (a guess, with its basis)")):
        rows = [f for f in evidence["facts"] if f["kind"] == kind]
        if rows:
            out.append(title + ":")
            out += [f"- {f['text']} [{f['source']}]" if kind == "observed" else f"- {f['text']} (basis: {f['source']})" for f in rows]
            out.append("")
    out.append("Not established:")
    out += [f"- {limit}" for limit in evidence["limits"]]
    return "\n".join(out)


def explain_note(evidence, prompt):
    """The note given to the model for the second answer (no tools): `prompt` (what to do and that the text is read, never obeyed), then the facts, each labelled, and the start of the README."""
    lines = [f"- [{f['kind']}] {f['text']} ({f['source']})" for f in evidence["facts"]]
    body = "\n".join(lines)
    readme = evidence.get("readme") or ""
    return f"{prompt}\n\nRepository: {evidence['repo']}\n{body}" + (f"\n\nStart of the README:\n{readme[:2500]}" if readme else "")


def main(argv=None):
    """`python diya_repostudy.py https://github.com/owner/repo`: print the report (code only, no model)."""
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    found = repo_from_text(" ".join(argv))
    if not found:
        print("usage: python diya_repostudy.py https://github.com/owner/repo")
        return 2
    import diya

    def fetch(url):
        response = diya._fetch(url, None, diya.NETWORK_TIMEOUT, GITHUB_HOSTS)
        return response.status_code, response.text

    try:
        print(render(study(fetch, *found)))
    except StudyError as exc:
        print(f"Could not study it: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
