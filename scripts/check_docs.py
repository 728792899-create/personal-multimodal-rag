from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)]+)\)")
IMAGE_LINK = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:")


def markdown_files() -> list[Path]:
    root_docs = sorted(ROOT.glob("*.md"))
    nested_docs = sorted((ROOT / "docs").rglob("*.md"))
    return [*root_docs, *nested_docs]


def clean_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    elif " \"" in target:
        target = target.split(" \"", 1)[0]
    return unquote(target)


def check_markdown(path: Path) -> list[str]:
    errors: list[str] = []
    content = path.read_text(encoding="utf-8")
    for match in IMAGE_LINK.finditer(content):
        if not match.group(1).strip():
            errors.append(f"{path.relative_to(ROOT)}: image is missing alt text")
    for match in MARKDOWN_LINK.finditer(content):
        target = clean_target(match.group(2))
        if not target or target.startswith("#") or target.startswith(EXTERNAL_SCHEMES):
            continue
        file_part = target.split("#", 1)[0].split("?", 1)[0]
        if not file_part:
            continue
        resolved = (path.parent / file_part).resolve()
        try:
            resolved.relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"{path.relative_to(ROOT)}: link escapes repository: {target}")
            continue
        if not resolved.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing link target: {target}")
    return errors


def check_svg(path: Path) -> list[str]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [f"{path.relative_to(ROOT)}: invalid SVG XML: {exc}"]
    title = root.find("{http://www.w3.org/2000/svg}title")
    description = root.find("{http://www.w3.org/2000/svg}desc")
    errors = []
    if title is None or not (title.text or "").strip():
        errors.append(f"{path.relative_to(ROOT)}: SVG is missing a title")
    if description is None or not (description.text or "").strip():
        errors.append(f"{path.relative_to(ROOT)}: SVG is missing a description")
    if root.get("role") != "img":
        errors.append(f"{path.relative_to(ROOT)}: SVG role must be img")
    return errors


def main() -> int:
    docs = markdown_files()
    svgs = sorted((ROOT / "docs" / "assets").glob("*.svg"))
    errors = [error for path in docs for error in check_markdown(path)]
    errors.extend(error for path in svgs for error in check_svg(path))
    if errors:
        print("Documentation checks failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Documentation checks passed: {len(docs)} Markdown files, {len(svgs)} SVG files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
