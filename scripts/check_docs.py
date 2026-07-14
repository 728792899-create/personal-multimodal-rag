from __future__ import annotations

import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)]+)\)")
IMAGE_LINK = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
SOCIAL_PREVIEW = ROOT / "docs" / "assets" / "social-preview.png"
SOCIAL_PREVIEW_SIZE = (1280, 640)
MAX_SOCIAL_PREVIEW_BYTES = 1_000_000


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


def png_dimensions(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as image:
        header = image.read(24)
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", header[16:24])


def check_raster(path: Path) -> list[str]:
    errors: list[str] = []
    header = path.read_bytes()[:8]
    suffix = path.suffix.lower()
    if suffix == ".png" and header != PNG_SIGNATURE:
        errors.append(f"{path.relative_to(ROOT)}: .png extension does not match PNG content")
    if suffix in {".jpg", ".jpeg"} and not header.startswith(JPEG_SIGNATURE):
        errors.append(f"{path.relative_to(ROOT)}: JPEG extension does not match JPEG content")
    return errors


def check_manifest(directory: Path, manifest: Path, patterns: tuple[str, ...]) -> list[str]:
    content = manifest.read_text(encoding="utf-8")
    assets = sorted(
        path
        for pattern in patterns
        for path in directory.glob(pattern)
        if path.name != manifest.name
    )
    return [
        f"{manifest.relative_to(ROOT)}: missing asset entry for {asset.name}"
        for asset in assets
        if f"`{asset.name}`" not in content
    ]


def check_social_preview() -> list[str]:
    errors: list[str] = []
    if not SOCIAL_PREVIEW.exists():
        return ["docs/assets/social-preview.png: social preview is missing"]
    dimensions = png_dimensions(SOCIAL_PREVIEW)
    if dimensions != SOCIAL_PREVIEW_SIZE:
        errors.append(
            "docs/assets/social-preview.png: expected "
            f"{SOCIAL_PREVIEW_SIZE[0]}x{SOCIAL_PREVIEW_SIZE[1]}, got {dimensions}"
        )
    size = SOCIAL_PREVIEW.stat().st_size
    if size >= MAX_SOCIAL_PREVIEW_BYTES:
        errors.append(
            "docs/assets/social-preview.png: expected a file smaller than "
            f"{MAX_SOCIAL_PREVIEW_BYTES} bytes, got {size}"
        )
    return errors


def main() -> int:
    docs = markdown_files()
    assets_dir = ROOT / "docs" / "assets"
    screenshots_dir = ROOT / "docs" / "screenshots"
    svgs = sorted(assets_dir.glob("*.svg"))
    rasters = sorted(
        path
        for directory in (assets_dir, screenshots_dir)
        for pattern in ("*.png", "*.jpg", "*.jpeg")
        for path in directory.glob(pattern)
    )
    errors = [error for path in docs for error in check_markdown(path)]
    errors.extend(error for path in svgs for error in check_svg(path))
    errors.extend(error for path in rasters for error in check_raster(path))
    errors.extend(check_manifest(assets_dir, assets_dir / "README.md", ("*.svg", "*.png", "*.jpg", "*.jpeg")))
    errors.extend(
        check_manifest(
            screenshots_dir,
            screenshots_dir / "README.md",
            ("*.png", "*.jpg", "*.jpeg"),
        )
    )
    errors.extend(check_social_preview())
    if errors:
        print("Documentation checks failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "Documentation checks passed: "
        f"{len(docs)} Markdown files, {len(svgs)} SVG files, {len(rasters)} raster images"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
