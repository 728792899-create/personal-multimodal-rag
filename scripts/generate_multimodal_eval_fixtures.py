from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "samples" / "multimodal-fixtures" / "images"
LABELS = [
    ("IMG-01", "RETRIEVAL FUNNEL", "48 BM25  ->  5 CITATIONS"),
    ("IMG-02", "VECTOR SPACE", "QueryStar  0.91  EvidenceMoon"),
    ("IMG-03", "MMR DIVERSITY", "Alpha  Beta  Gamma"),
    ("IMG-04", "CITATION COVERAGE", "7 / 8  =  87.5%"),
    ("IMG-05", "REFUSAL GATE", "0.03  <  0.05"),
    ("IMG-06", "INDEX QUEUE", "queued  running  quality  succeeded"),
    ("IMG-07", "DOCUMENT ELEMENTS", "heading  paragraph  table  equation"),
    ("IMG-08", "GRAPH PATH", "RouterNode -> RankerNode -> CitationNode"),
    ("IMG-09", "PROVIDER HEALTH", "template ready / OpenAI not_configured"),
    ("IMG-10", "MOBILE LAYOUT", "390 px / single column"),
    ("IMG-11", "ERROR RECOVERY", "504 / request ID / retry"),
    ("IMG-12", "FEEDBACK LOOP", "bad_answer -> eval draft -> regression"),
]


def font(size: int):
    for candidate in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def generate() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for index, (marker, title, detail) in enumerate(LABELS, start=1):
        image = Image.new("RGB", (640, 360), "#f4f7f5")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((32, 28, 608, 332), radius=28, fill="#ffffff", outline="#b9c8c1", width=3)
        accent = (24 + index * 9, 116 + (index % 4) * 14, 104 + (index % 3) * 18)
        draw.rounded_rectangle((64, 62, 178, 108), radius=13, fill=accent)
        draw.text((83, 73), marker, font=font(20), fill="white")
        draw.text((64, 142), title, font=font(30), fill="#16231e")
        draw.text((64, 196), detail, font=font(20), fill="#42564e")
        for step in range(4):
            x = 72 + step * 132
            draw.rounded_rectangle((x, 258, x + 94, 282), radius=10, fill=accent if step <= index % 4 else "#dfe8e4")
        image.save(TARGET / f"img-{index:02d}.png", format="PNG", optimize=True)


def check() -> None:
    files = sorted(TARGET.glob("img-*.png"))
    if len(files) != len(LABELS):
        raise SystemExit(f"Expected {len(LABELS)} image fixtures, found {len(files)}")
    for path in files:
        if path.stat().st_size > 1_000_000:
            raise SystemExit(f"Fixture exceeds 1 MB: {path}")
        with Image.open(path) as image:
            if image.format != "PNG" or image.size != (640, 360) or int(getattr(image, "n_frames", 1)) != 1:
                raise SystemExit(f"Invalid fixture contract: {path}")
            image.verify()
    print(f"Multimodal fixtures passed: {len(files)} PNG files at 640x360")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    check() if args.check else generate()


if __name__ == "__main__":
    main()
