from __future__ import annotations

import re
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from functools import lru_cache
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


@lru_cache(maxsize=1)
def versioned_paths() -> set[Path] | None:
    """Return files that belong to the Git deliverable.

    Local screenshot drafts and Finder-style duplicate copies must not make
    documentation CI nondeterministic. Staged files are included by
    ``git ls-files``; non-Git source archives fall back to scanning everything.
    """

    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return {
        (ROOT / item.decode("utf-8")).resolve()
        for item in result.stdout.split(b"\0")
        if item
    }


def belongs_to_deliverable(path: Path) -> bool:
    tracked = versioned_paths()
    return tracked is None or path.resolve() in tracked


def markdown_files() -> list[Path]:
    root_docs = sorted(path for path in ROOT.glob("*.md") if belongs_to_deliverable(path))
    nested_docs = sorted(
        path for path in (ROOT / "docs").rglob("*.md") if belongs_to_deliverable(path)
    )
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
            errors.append(f"{path.relative_to(ROOT)}：图片缺少 alt 文本")
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
            errors.append(f"{path.relative_to(ROOT)}：链接超出仓库范围：{target}")
            continue
        if not resolved.exists():
            errors.append(f"{path.relative_to(ROOT)}：链接目标不存在：{target}")
    return errors


def check_svg(path: Path) -> list[str]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [f"{path.relative_to(ROOT)}：SVG XML 无效：{exc}"]
    title = root.find("{http://www.w3.org/2000/svg}title")
    description = root.find("{http://www.w3.org/2000/svg}desc")
    errors = []
    if title is None or not (title.text or "").strip():
        errors.append(f"{path.relative_to(ROOT)}：SVG 缺少 title")
    if description is None or not (description.text or "").strip():
        errors.append(f"{path.relative_to(ROOT)}：SVG 缺少 description")
    if root.get("role") != "img":
        errors.append(f"{path.relative_to(ROOT)}：SVG role 必须为 img")
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
        errors.append(f"{path.relative_to(ROOT)}：.png 扩展名与 PNG 内容不匹配")
    if suffix in {".jpg", ".jpeg"} and not header.startswith(JPEG_SIGNATURE):
        errors.append(f"{path.relative_to(ROOT)}：JPEG 扩展名与 JPEG 内容不匹配")
    return errors


def check_manifest(directory: Path, manifest: Path, patterns: tuple[str, ...]) -> list[str]:
    content = manifest.read_text(encoding="utf-8")
    assets = sorted(
        path
        for pattern in patterns
        for path in directory.glob(pattern)
        if path.name != manifest.name
        and belongs_to_deliverable(path)
    )
    return [
        f"{manifest.relative_to(ROOT)}：缺少资源清单项 {asset.name}"
        for asset in assets
        if f"`{asset.name}`" not in content
    ]


def check_social_preview() -> list[str]:
    errors: list[str] = []
    if not SOCIAL_PREVIEW.exists():
        return ["docs/assets/social-preview.png：缺少社交预览图"]
    dimensions = png_dimensions(SOCIAL_PREVIEW)
    if dimensions != SOCIAL_PREVIEW_SIZE:
        errors.append(
            "docs/assets/social-preview.png：预期尺寸为 "
            f"{SOCIAL_PREVIEW_SIZE[0]}x{SOCIAL_PREVIEW_SIZE[1]}，实际为 {dimensions}"
        )
    size = SOCIAL_PREVIEW.stat().st_size
    if size >= MAX_SOCIAL_PREVIEW_BYTES:
        errors.append(
            "docs/assets/social-preview.png：文件应小于 "
            f"{MAX_SOCIAL_PREVIEW_BYTES} 字节，实际为 {size} 字节"
        )
    return errors


def main() -> int:
    docs = markdown_files()
    assets_dir = ROOT / "docs" / "assets"
    screenshots_dir = ROOT / "docs" / "screenshots"
    svgs = sorted(path for path in assets_dir.glob("*.svg") if belongs_to_deliverable(path))
    rasters = sorted(
        path
        for directory in (assets_dir, screenshots_dir)
        for pattern in ("*.png", "*.jpg", "*.jpeg")
        for path in directory.glob(pattern)
        if belongs_to_deliverable(path)
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
        print("文档检查失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "文档检查通过："
        f"{len(docs)} 个 Markdown 文件、{len(svgs)} 个 SVG 文件、{len(rasters)} 张栅格图片"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
