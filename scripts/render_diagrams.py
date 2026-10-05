"""Render the Mermaid diagram sources of the documentation to PNG images.

Every `docs/assets/diagrams/<name>.mmd` file is rendered to `<name>-light.png` and
`<name>-dark.png` with Mermaid CLI. Node.js must be installed. Set
`MERMAID_BROWSER` to the path of an installed Chromium-based browser to reuse it
instead of downloading one.

Usage:
    python scripts/render_diagrams.py           # render every diagram
    python scripts/render_diagrams.py --check   # verify the images are present
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIAGRAMS = ROOT / "docs" / "assets" / "diagrams"
MERMAID_CLI = "@mermaid-js/mermaid-cli@12.0.0"
THEMES = {"light": "default", "dark": "dark"}
MERMAID_CONFIG = {
    "fontFamily": "'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    "flowchart": {"curve": "basis", "padding": 14, "wrappingWidth": 320},
    "sequence": {"mirrorActors": False},
}


def images(source: Path) -> list[Path]:
    return [source.with_name(f"{source.stem}-{variant}.png") for variant in THEMES]


def check() -> int:
    sources = sorted(DIAGRAMS.glob("*.mmd"))
    expected = {image for source in sources for image in images(source)}
    missing = sorted(image.name for image in expected if not image.exists())
    stray = sorted(
        image.name for image in DIAGRAMS.glob("*.png") if image not in expected
    )
    for name in missing:
        print(f"missing image: {name}")
    for name in stray:
        print(f"image without a source: {name}")
    if missing or stray:
        return 1
    print(f"{len(sources)} diagrams have light and dark images")
    return 0


def render() -> int:
    npx = shutil.which("npx")
    if npx is None:
        print("Node.js (npx) is required to render diagrams")
        return 1
    environment = dict(os.environ)
    puppeteer: dict[str, object] = {}
    browser = os.environ.get("MERMAID_BROWSER")
    if browser:
        puppeteer["executablePath"] = browser
        environment["PUPPETEER_SKIP_DOWNLOAD"] = "true"
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / "mermaid.json"
        config.write_text(json.dumps(MERMAID_CONFIG), encoding="utf-8")
        puppeteer_config = Path(directory) / "puppeteer.json"
        puppeteer_config.write_text(json.dumps(puppeteer), encoding="utf-8")
        for source in sorted(DIAGRAMS.glob("*.mmd")):
            for (variant, theme), image in zip(
                THEMES.items(), images(source), strict=True
            ):
                subprocess.run(
                    [
                        npx,
                        "--yes",
                        MERMAID_CLI,
                        "--input",
                        str(source),
                        "--output",
                        str(image),
                        "--theme",
                        theme,
                        "--backgroundColor",
                        "transparent",
                        "--scale",
                        "2",
                        "--configFile",
                        str(config),
                        "--puppeteerConfigFile",
                        str(puppeteer_config),
                        "--quiet",
                    ],
                    check=True,
                    env=environment,
                )
                print(f"rendered {image.relative_to(ROOT).as_posix()} ({variant})")
    return check()


def main() -> int:
    parser = argparse.ArgumentParser(description="Render documentation diagrams.")
    parser.add_argument(
        "--check", action="store_true", help="only verify that the images exist"
    )
    arguments = parser.parse_args()
    return check() if arguments.check else render()


if __name__ == "__main__":
    sys.exit(main())
