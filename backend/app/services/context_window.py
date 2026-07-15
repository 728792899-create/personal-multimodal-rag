from __future__ import annotations

import math

from app.models.domain import Document, DocumentElement


class ContextWindowBuilder:
    """Build bounded, provenance-preserving context around one document element."""

    def __init__(self, max_context_chars: int = 8_000):
        self.max_context_chars = max(32, int(max_context_chars))

    def build(
        self,
        document: Document,
        target: DocumentElement,
        *,
        page_window: int = 1,
        element_window: int = 4,
    ) -> dict:
        ordered = sorted(document.elements, key=lambda item: item.order)
        target_index = next(
            (index for index, element in enumerate(ordered) if element.element_id == target.element_id),
            0,
        )
        if target.page_number is not None:
            candidates = [
                (index, element)
                for index, element in enumerate(ordered)
                if element.page_number is not None
                and abs(int(element.page_number) - int(target.page_number)) <= max(0, page_window)
            ]
        else:
            candidates = [
                (index, element)
                for index, element in enumerate(ordered)
                if abs(index - target_index) <= max(0, element_window)
            ]
        candidates.sort(key=lambda item: (abs(item[0] - target_index), item[0]))

        selected: list[tuple[int, DocumentElement, str]] = []
        consumed = 0
        for index, element in candidates:
            rendered = self._render(element)
            if not rendered:
                continue
            separator = 2 if selected else 0
            remaining = self.max_context_chars - consumed - separator
            if remaining <= 0:
                continue
            if index == target_index and len(rendered) > remaining:
                rendered = rendered[:remaining]
            elif len(rendered) > remaining:
                continue
            selected.append((index, element, rendered))
            consumed += separator + len(rendered)

        if not any(element.element_id == target.element_id for _, element, _ in selected):
            rendered = self._render(target)[: self.max_context_chars]
            selected = [(target_index, target, rendered)]
        selected.sort(key=lambda item: item[0])
        text = "\n\n".join(item[2] for item in selected)[: self.max_context_chars]
        return {
            "text": text,
            "element_ids": [item[1].element_id for item in selected],
            "page_numbers": list(
                dict.fromkeys(item[1].page_number for item in selected if item[1].page_number is not None)
            ),
            "character_count": len(text),
            "token_estimate": math.ceil(len(text) / 4),
            "truncated": len(text) >= self.max_context_chars,
        }

    @staticmethod
    def _render(element: DocumentElement) -> str:
        parts: list[str] = []
        if element.heading_path:
            parts.append(" > ".join(element.heading_path))
        if element.text:
            parts.append(element.text)
        if element.caption and element.caption not in parts:
            parts.append(f"Caption: {element.caption}")
        if element.footnotes:
            parts.append("Footnotes: " + " ".join(element.footnotes))
        return "\n".join(part for part in parts if part).strip()
