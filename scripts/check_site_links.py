"""Verify local page, asset, and fragment links in the built documentation site."""

from __future__ import annotations

import sys
import tomllib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Page(HTMLParser):
    """Collect link targets and anchors."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.anchors: set[str] = set()
        self.links: list[str] = []
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if anchor := attributes.get("id"):
            self.anchors.add(anchor)
        for key in ("href", "src"):
            if target := attributes.get(key):
                self.links.append(target)


def main() -> int:
    root = Path(__file__).resolve().parents[1] / "site"
    config = tomllib.loads((root.parent / "zensical.toml").read_text(encoding="utf-8"))
    base_path = urlsplit(config["project"]["site_url"]).path
    pages = {path.resolve(): Page(path) for path in root.rglob("*.html")}
    if not pages:
        print("No built site found; run zensical build --strict first.", file=sys.stderr)
        return 1
    errors = []
    checked = 0
    for path, page in pages.items():
        for link in page.links:
            parts = urlsplit(link)
            if parts.scheme or parts.netloc:
                continue
            checked += 1
            local_path = unquote(parts.path)
            if local_path.startswith(base_path):
                local_path = "/" + local_path[len(base_path) :]
            target = (
                root / local_path.lstrip("/")
                if local_path.startswith("/")
                else path.parent / local_path
                if local_path
                else path
            ).resolve()
            if target.is_dir():
                target /= "index.html"
            if not target.is_file():
                errors.append(f"{path.relative_to(root)}: missing {link}")
            elif parts.fragment and target in pages:
                fragment = unquote(parts.fragment)
                if fragment not in pages[target].anchors and not fragment.startswith("only-"):
                    errors.append(f"{path.relative_to(root)}: missing anchor {link}")
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Checked {checked} local links in {len(pages)} pages; {len(errors)} errors.")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
