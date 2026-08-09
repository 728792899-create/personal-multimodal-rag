from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.document_processor import DocumentProcessor  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("用法：python scripts/ingest_file.py <文件>")

    file_path = Path(sys.argv[1])
    processor = DocumentProcessor()
    document = processor.parse_file(file_path)
    chunks = processor.split(document)

    print(f"document_id={document.document_id}")
    print(f"file_name={document.file_name}")
    print(f"file_type={document.file_type}")
    print(f"chunks={len(chunks)}")
    for chunk in chunks[:3]:
        print(f"- {chunk.chunk_id} page={chunk.page_number} heading={' > '.join(chunk.heading_path) or '-'}")


if __name__ == "__main__":
    main()
