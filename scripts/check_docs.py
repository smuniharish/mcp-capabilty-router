"""Check the Markdown documentation published with the project.

The checker reads the README, the project documents, the documentation site, the
examples guide, and the Agent Skill, and verifies that:

- every Python code block compiles and imports only public names from
  `mcp_capability_router`;
- every Python code block preceded by `<!-- test -->` runs successfully with
  warnings treated as errors and prints exactly the following `text` block, or
  nothing when no `text` block follows;
- the templates of the Agent Skill run successfully;
- every public name is documented exactly once in the API reference, and the
  Agent Skill and the changelog describe the current version;
- no Mermaid code block is used, because diagrams are committed as images;
- relative links, links into this repository, and links into the documentation
  site point to files, pages, and headings that exist, and the README uses
  absolute links so that it renders on PyPI;
- published text does not mention internal modules, decision records, or local
  paths.

Blocks that include files with `--8<--` are skipped; the examples they include are
verified by `scripts/run_examples.py`.

Usage:
    python scripts/check_docs.py
"""

from __future__ import annotations

import ast
import difflib
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

import mcp_capability_router

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
REPOSITORY = "https://github.com/smuniharish/mcp-capabilty-router/"
RAW = "https://raw.githubusercontent.com/smuniharish/mcp-capabilty-router/"
SITE = "https://mcp-capabilty-router.readthedocs.io/en/latest/"
BRANCHES = frozenset({"HEAD", "master"})
PATTERNS = (
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/**/*.md",
    "benchmarks/README.md",
    "examples/README.md",
    "mcp-capability-router-skills/**/*.md",
)
ABSOLUTE_ONLY = frozenset({"README.md", "CHANGELOG.md"})
CONTRIBUTOR_DOCUMENTS = frozenset(
    {"CONTRIBUTING.md", "mcp-capability-router-skills/validation/README.md"}
)
PUBLIC = frozenset(mcp_capability_router.__all__) | {"__version__"}
TEMPLATES = "mcp-capability-router-skills/skills/*/assets/*.py"
SKILL = "mcp-capability-router-skills/skills/mcp-capability-router/SKILL.md"
SKILL_VERSION = re.compile(r'(?m)^  version: "(?P<version>[^"]+)"$')
API_ENTRY = re.compile(r"^::: mcp_capability_router\.(?P<name>\w+)\s*$")
TEST_MARKER = "<!-- test -->"
OPENING = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^`]*)$")
HEADING = re.compile(r"^(?P<level>#{1,6})[ \t]+(?P<text>.+?)[ \t]*#*[ \t]*$")
CUSTOM_ID = re.compile(r"[ \t]*\{[^}]*#(?P<id>[\w-]+)[^}]*\}[ \t]*$")
INCLUDE = re.compile(r'^[ \t]*--8<--[ \t]+"(?P<path>[^"]+)"[ \t]*$')
MARKDOWN_LINK = re.compile(
    r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\((?P<target><[^>]+>|[^)\s]+)(?:[ \t]+\"[^\"]*\")?\)"
)
HTML_LINK = re.compile(r"\b(?:href|src|srcset)=\"(?P<target>[^\"]+)\"")
INLINE_CODE = re.compile(r"`+[^`]*`+")
# langsmith, a LangChain dependency, calls asyncio.iscoroutinefunction, which Python
# 3.14 deprecates; every other warning is an error.
WARNING_OPTIONS = (
    "-W",
    "error",
    "-W",
    "ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning",
)


@dataclass(frozen=True, slots=True)
class Rule:
    """A pattern that must not appear in published text."""

    pattern: re.Pattern[str]
    message: str
    applies: Callable[[str], bool]


RULES = (
    Rule(
        re.compile(r"\bADRs?\b|decisions\.md"),
        "architecture decision records are not published",
        lambda name: True,
    ),
    Rule(
        re.compile(r"\b_internal\b"),
        "internal modules are not part of the documented API",
        lambda name: name not in CONTRIBUTOR_DOCUMENTS,
    ),
    Rule(
        re.compile(r"\b[A-Za-z]:\\Users\\|(?<![\w.])/Users/"),
        "local paths must not be published",
        lambda name: True,
    ),
)


@dataclass(slots=True)
class Fence:
    """A fenced code block."""

    info: str
    line: int
    body: str
    tested: bool


@dataclass(slots=True)
class Document:
    """A parsed Markdown document."""

    path: Path
    name: str
    lines: list[str]
    fences: list[Fence] = field(default_factory=list)
    prose: list[tuple[int, str]] = field(default_factory=list)


@dataclass(slots=True)
class Report:
    """Problems found and work done."""

    problems: list[str] = field(default_factory=list)
    blocks: int = 0
    executed: int = 0
    links: int = 0

    def add(self, document: Document, line: int, message: str) -> None:
        self.problems.append(f"{document.name}:{line}: {message}")


def dedent(line: str, indent: int) -> str:
    """Remove the indentation of the fence that contains `line`."""
    prefix = line[:indent]
    return line[indent:] if not prefix or prefix.isspace() else line.lstrip()


def parse(path: Path) -> Document:
    """Split a Markdown file into fenced code blocks and prose lines."""
    lines = path.read_text(encoding="utf-8").splitlines()
    document = Document(path, path.relative_to(ROOT).as_posix(), lines)
    previous = ""
    index = 0
    while index < len(lines):
        opening = OPENING.match(lines[index])
        if opening is None:
            document.prose.append((index + 1, lines[index]))
            if lines[index].strip():
                previous = lines[index].strip()
            index += 1
            continue
        indent = len(opening["indent"])
        fence = opening["fence"]
        closing = re.compile(rf"^[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$")
        body: list[str] = []
        start = index + 1
        index += 1
        while index < len(lines) and not closing.match(lines[index]):
            body.append(dedent(lines[index], indent))
            index += 1
        info = opening["info"].split()
        document.fences.append(
            Fence(
                info=info[0].lower() if info else "",
                line=start,
                body="\n".join(body) + "\n",
                tested=previous == TEST_MARKER,
            )
        )
        previous = ""
        index += 1
    return document


def python_markdown_slug(text: str) -> str:
    """Return the anchor Python-Markdown generates for a heading."""
    value = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def github_slug(text: str) -> str:
    """Return the anchor GitHub generates for a heading."""
    value = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return value.replace(" ", "-")


def heading_text(raw: str) -> str:
    """Return the visible text of a Markdown heading."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", raw)
    text = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("`", "")


def anchors(
    path: Path, *, github: bool, seen: frozenset[Path] = frozenset()
) -> set[str]:
    """Return the heading anchors of a Markdown file, including included files."""
    document = parse(path)
    found: set[str] = set()
    counts: dict[str, int] = {}
    for _, line in document.prose:
        include = INCLUDE.match(line)
        if include is not None and not github:
            target = (ROOT / include["path"]).resolve()
            if target.suffix == ".md" and target not in seen and target.exists():
                found |= anchors(target, github=github, seen=seen | {path})
            continue
        heading = HEADING.match(line)
        if heading is None:
            continue
        custom = CUSTOM_ID.search(heading["text"])
        if custom is not None and not github:
            found.add(custom["id"])
            continue
        text = heading_text(heading["text"])
        slug = github_slug(text) if github else python_markdown_slug(text)
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        separator = "-" if github else "_"
        found.add(slug if count == 0 else f"{slug}{separator}{count}")
    return found


def site_page(path: str) -> Path | None:
    """Map a documentation-site URL path to its Markdown source."""
    stem = path.strip("/")
    candidates = (
        [DOCS / "index.md"]
        if not stem
        else [DOCS / f"{stem}.md", DOCS / stem / "index.md"]
    )
    return next((candidate for candidate in candidates if candidate.exists()), None)


def check_anchor(page: Path, fragment: str, *, github: bool) -> str | None:
    """Return a problem if `fragment` is not an anchor of `page`."""
    if not fragment or page.suffix != ".md":
        return None
    if fragment.startswith("mcp_capability_router."):
        name = fragment.split(".")[1]
        text = page.read_text(encoding="utf-8")
        if name in PUBLIC and f"::: mcp_capability_router.{name}" in text:
            return None
        return f"{page.relative_to(ROOT).as_posix()} does not document {fragment}"
    if fragment in anchors(page, github=github):
        return None
    return f"{page.relative_to(ROOT).as_posix()} has no heading #{fragment}"


def check_repository_link(path: str, fragment: str) -> str | None:
    """Check a link into this repository on GitHub."""
    kind, _, rest = path.partition("/")
    branch, _, relative = rest.partition("/")
    if kind not in {"blob", "tree", "raw"}:
        return None
    if branch not in BRANCHES:
        return f"link to the {branch!r} branch; use HEAD or master"
    target = ROOT / relative
    if not target.exists():
        return f"repository path {relative!r} does not exist"
    return check_anchor(target, fragment, github=True)


def check_link(document: Document, target: str) -> str | None:
    """Return a problem with a link, or `None` if it resolves."""
    target = target.strip("<>").split()[0]
    url = urlsplit(target)
    path = unquote(url.path)
    if target.startswith(REPOSITORY):
        relative = path.removeprefix("/smuniharish/mcp-capabilty-router/")
        return check_repository_link(relative, url.fragment)
    if target.startswith(RAW):
        relative = path.removeprefix("/smuniharish/mcp-capabilty-router/")
        return check_repository_link(f"raw/{relative}", url.fragment)
    if target.startswith(SITE):
        page = site_page(path.removeprefix(urlsplit(SITE).path))
        if page is None:
            return f"documentation page {target!r} does not exist"
        return check_anchor(page, url.fragment, github=False)
    if url.scheme or target.startswith("//"):
        return None
    if document.name in ABSOLUTE_ONLY and path:
        return f"relative link {target!r}; this file is rendered outside the repository"
    if document.path.is_relative_to(DOCS):
        return None
    resolved = (document.path.parent / path).resolve() if path else document.path
    if not resolved.exists():
        return f"relative link {target!r} does not resolve"
    return check_anchor(resolved, url.fragment, github=True)


def strip_inline_code(line: str) -> str:
    return INLINE_CODE.sub("", line)


def check_prose(document: Document, report: Report) -> None:
    """Check the links and wording of the text outside code blocks."""
    for number, line in document.prose:
        for rule in RULES:
            if rule.applies(document.name) and rule.pattern.search(line):
                report.add(document, number, rule.message)
        text = strip_inline_code(line)
        for match in (*MARKDOWN_LINK.finditer(text), *HTML_LINK.finditer(text)):
            report.links += 1
            problem = check_link(document, match["target"])
            if problem is not None:
                report.add(document, number, problem)


def imported_names(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """Yield problems with the `mcp_capability_router` names used by a code block."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module.startswith("mcp_capability_router."):
                yield (
                    node.lineno,
                    f"imports from {node.module}; import from mcp_capability_router",
                )
            elif node.module == "mcp_capability_router":
                for alias in node.names:
                    if alias.name not in PUBLIC:
                        yield node.lineno, f"imports non-public name {alias.name!r}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("mcp_capability_router."):
                    yield (
                        node.lineno,
                        f"imports {alias.name}; import from mcp_capability_router",
                    )
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "mcp_capability_router"
            and node.attr not in PUBLIC
        ):
            yield node.lineno, f"uses non-public name mcp_capability_router.{node.attr}"


def run_script(script: Path) -> subprocess.CompletedProcess[str]:
    """Run a Python file in a fresh interpreter with warnings as errors."""
    return subprocess.run(
        [sys.executable, *WARNING_OPTIONS, script.name],
        cwd=script.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        timeout=120,
        check=False,
    )


def run(code: str) -> subprocess.CompletedProcess[str]:
    """Run a code block in a temporary directory."""
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory, "snippet.py")
        script.write_text(code, encoding="utf-8")
        return run_script(script)


def check_templates(report: Report) -> int:
    """Run the Agent Skill's templates and return how many ran."""
    templates = sorted(ROOT.glob(TEMPLATES))
    for template in templates:
        completed = run_script(template)
        if completed.returncode != 0 or completed.stderr:
            report.problems.append(
                f"{template.relative_to(ROOT).as_posix()}: failed "
                f"(exit code {completed.returncode}):\n{completed.stderr.rstrip()}"
            )
    return len(templates)


def check_fences(document: Document, report: Report) -> None:
    """Compile, inspect, and run the code blocks of a document."""
    for position, fence in enumerate(document.fences):
        if fence.info == "mermaid":
            report.add(document, fence.line, "render Mermaid diagrams to images")
        if fence.info not in {"python", "py"} or "--8<--" in fence.body:
            if fence.tested:
                report.add(document, fence.line, "only Python blocks can be tested")
            continue
        report.blocks += 1
        try:
            tree = compile(
                fence.body,
                f"{document.name}:{fence.line}",
                "exec",
                flags=ast.PyCF_ONLY_AST | ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
                dont_inherit=True,
            )
        except SyntaxError as error:
            line = fence.line + (error.lineno or 1)
            report.add(document, line, f"code block does not compile: {error.msg}")
            continue
        for offset, problem in imported_names(tree):
            report.add(document, fence.line + offset, problem)
        if not fence.tested:
            continue
        report.executed += 1
        following = document.fences[position + 1 : position + 2]
        expected = (
            following[0].body if following and following[0].info == "text" else ""
        )
        completed = run(fence.body)
        stdout = completed.stdout.replace("\r\n", "\n")
        if completed.returncode != 0 or completed.stderr:
            report.add(
                document,
                fence.line,
                f"code block failed (exit code {completed.returncode}):\n"
                f"{completed.stderr.rstrip()}",
            )
        elif stdout != expected:
            diff = "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    stdout.splitlines(keepends=True),
                    "documented",
                    "actual",
                )
            )
            report.add(document, fence.line, f"code block printed:\n{diff.rstrip()}")


def check_consistency(report: Report) -> None:
    """Check the API reference, the skill, and the changelog against the package."""
    documented: dict[str, list[str]] = {}
    for page in sorted((DOCS / "api").glob("*.md")):
        for line in page.read_text(encoding="utf-8").splitlines():
            if match := API_ENTRY.match(line):
                name = page.relative_to(ROOT).as_posix()
                documented.setdefault(match["name"], []).append(name)
    for name in sorted(PUBLIC - {"__version__"}):
        pages = documented.get(name, [])
        if len(pages) != 1:
            report.problems.append(
                f"docs/api: mcp_capability_router.{name} is documented "
                f"{len(pages)} times"
            )
    for name in sorted(set(documented) - PUBLIC):
        report.problems.append(f"docs/api: mcp_capability_router.{name} is not public")
    version = mcp_capability_router.__version__
    skill = ROOT / SKILL
    if skill.exists():
        found = SKILL_VERSION.search(skill.read_text(encoding="utf-8"))
        if found is None or found["version"] != version:
            report.problems.append(f"{SKILL}: metadata.version must be {version!r}")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{version}]" not in changelog:
        report.problems.append(f"CHANGELOG.md: no section for version {version}")


def documents() -> list[Path]:
    """Return every Markdown file covered by the checker."""
    found: set[Path] = set()
    for pattern in PATTERNS:
        found.update(ROOT.glob(pattern))
    return sorted(found)


def main() -> int:
    report = Report()
    paths = documents()
    for path in paths:
        document = parse(path)
        check_fences(document, report)
        check_prose(document, report)
    templates = check_templates(report)
    check_consistency(report)
    for problem in report.problems:
        print(problem)
    print(
        f"checked {len(paths)} files, {report.blocks} Python blocks "
        f"({report.executed} executed), {report.links} links, and {templates} "
        f"templates: {len(report.problems)} problem(s)"
    )
    return 1 if report.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
