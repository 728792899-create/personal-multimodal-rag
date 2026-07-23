from app.services.markdown_export import (
    export_answer_markdown,
    export_card_markdown,
    export_conversation_markdown,
)


def test_answer_export_keeps_citations_and_audit():
    markdown = export_answer_markdown(
        {
            "question": "What changed?",
            "answer": "The queue is durable. [1]",
            "confidence": 0.92,
            "created_at": "2026-07-23",
            "citations": [
                {
                    "filename": "operations.md",
                    "page_number": 2,
                    "snippet": "Redis Streams is fed by a transactional outbox.",
                }
            ],
        },
        title="Production evidence",
    )

    assert markdown.startswith("# Production evidence")
    assert "## Question" in markdown
    assert "**operations.md**, page 2" in markdown
    assert "Confidence: 0.92" in markdown


def test_conversation_export_includes_message_level_citations():
    markdown = export_conversation_markdown(
        {"id": "conversation-1", "title": "Release review", "updated_at": "2026-07-23"},
        [
            {"role": "user", "content": "Is it ready?", "metadata": {}},
            {
                "role": "assistant",
                "content": "It is an RC.",
                "metadata": {
                    "response": {
                        "citations": [{"filename": "release.md", "snippet": "14-day soak required"}]
                    }
                },
            },
        ],
    )

    assert "## User" in markdown
    assert "## Assistant" in markdown
    assert "14-day soak required" in markdown


def test_knowledge_card_export_sanitizes_heading_and_tags():
    markdown = export_card_markdown(
        {
            "title": "# Durable queue",
            "question": "Why outbox?",
            "answer": "Atomic publication.",
            "tags": ["redis", "job`queue"],
            "citations": [],
        }
    )

    assert markdown.startswith("# Durable queue")
    assert "`redis` `jobqueue`" in markdown
