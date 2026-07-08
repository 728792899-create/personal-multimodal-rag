from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
import json
from pathlib import Path

from app.models.domain import Document


class DocumentRegistry:
    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._ensure_schema()

    def save_document(self, document: Document) -> None:
        self.conn.execute(
            """
            INSERT INTO documents (document_id, payload)
            VALUES (?, ?)
            ON CONFLICT(document_id) DO UPDATE SET payload = excluded.payload
            """,
            (document.document_id, document.model_dump_json()),
        )
        self.conn.commit()

    def load_documents(self) -> list[Document]:
        rows = self.conn.execute("SELECT payload FROM documents ORDER BY document_id").fetchall()
        return [Document.model_validate_json(row[0]) for row in rows]

    def get_document(self, document_id: str) -> Document | None:
        row = self.conn.execute("SELECT payload FROM documents WHERE document_id = ?", (document_id,)).fetchone()
        return Document.model_validate_json(row[0]) if row else None

    def find_by_content_hash(self, content_hash: str) -> Document | None:
        if not content_hash:
            return None
        for document in self.load_documents():
            if document.metadata.get("content_hash") == content_hash:
                return document
        return None

    def update_document_status(self, document_id: str, status: str, error: str = "") -> Document | None:
        document = self.get_document(document_id)
        if not document:
            return None
        document.metadata["index_status"] = status
        document.metadata["index_error"] = error
        self.save_document(document)
        return document

    def delete_document(self, document_id: str) -> None:
        self.conn.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))
        self.conn.commit()

    def save_history(self, question: str, response: dict) -> dict:
        history_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        answer = response.get("answer", "")
        citations = response.get("citations", [])
        payload = {
            "id": history_id,
            "question": question,
            "answer": answer,
            "citations": citations,
            "retrieval_trace": response.get("retrieval_trace", {}),
            "generation_trace": response.get("generation_trace", {}),
            "confidence": response.get("confidence"),
            "created_at": created_at,
        }
        self.conn.execute(
            """
            INSERT INTO history (history_id, question, answer, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (history_id, question, answer, json.dumps(payload, ensure_ascii=False), created_at),
        )
        self.conn.commit()
        return payload

    def get_history(self, history_id: str) -> dict | None:
        row = self.conn.execute("SELECT payload FROM history WHERE history_id = ?", (history_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list_history(self, limit: int = 30) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload FROM history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def clear_history(self) -> None:
        self.conn.execute("DELETE FROM history")
        self.conn.commit()

    def save_feedback(self, payload: dict) -> dict:
        feedback_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        stored = {
            "id": feedback_id,
            "created_at": created_at,
            **payload,
        }
        self.conn.execute(
            """
            INSERT INTO feedback (feedback_id, history_id, rating, failure_type, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_id,
                stored.get("history_id") or "",
                stored.get("rating") or "",
                stored.get("failure_type") or "",
                json.dumps(stored, ensure_ascii=False),
                created_at,
            ),
        )
        self.conn.commit()
        return stored

    def list_feedback(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload FROM feedback ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def feedback_stats(self) -> dict:
        rows = self.conn.execute("SELECT payload FROM feedback ORDER BY created_at DESC").fetchall()
        feedback = [json.loads(row[0]) for row in rows]
        failure_types: dict[str, int] = {}
        for item in feedback:
            failure_type = item.get("failure_type") or "unclassified"
            failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
        return {
            "total": len(feedback),
            "positive": sum(1 for item in feedback if item.get("rating") == "up"),
            "negative": sum(1 for item in feedback if item.get("rating") == "down"),
            "failure_types": failure_types,
            "recent": feedback[:8],
        }

    def log_operation(self, event_type: str, message: str, payload: dict | None = None, level: str = "info") -> dict:
        operation_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        stored = {
            "id": operation_id,
            "event_type": event_type,
            "level": level,
            "message": message,
            "payload": payload or {},
            "created_at": created_at,
        }
        self.conn.execute(
            """
            INSERT INTO operation_logs (operation_id, event_type, level, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                event_type,
                level,
                json.dumps(stored, ensure_ascii=False),
                created_at,
            ),
        )
        self.conn.commit()
        return stored

    def list_operations(self, limit: int = 40) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload FROM operation_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_knowledge_card(self, payload: dict) -> dict:
        card_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        stored = {
            "id": card_id,
            "created_at": created_at,
            **payload,
        }
        self.conn.execute(
            """
            INSERT INTO knowledge_cards (card_id, title, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                card_id,
                stored.get("title") or "",
                json.dumps(stored, ensure_ascii=False),
                created_at,
            ),
        )
        self.conn.commit()
        return stored

    def list_knowledge_cards(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload FROM knowledge_cards ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete_knowledge_card(self, card_id: str) -> bool:
        cursor = self.conn.execute("DELETE FROM knowledge_cards WHERE card_id = ?", (card_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def save_eval_case(self, payload: dict) -> dict:
        case_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        stored = {
            "id": case_id,
            "created_at": created_at,
            "status": payload.get("status") or "draft",
            **payload,
        }
        self.conn.execute(
            """
            INSERT INTO eval_cases (case_id, question, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                case_id,
                stored.get("question") or "",
                json.dumps(stored, ensure_ascii=False),
                created_at,
            ),
        )
        self.conn.commit()
        return stored

    def list_eval_cases(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload FROM eval_cases ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def _ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
              document_id TEXT PRIMARY KEY,
              payload TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
              history_id TEXT PRIMARY KEY,
              question TEXT NOT NULL,
              answer TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
              feedback_id TEXT PRIMARY KEY,
              history_id TEXT,
              rating TEXT NOT NULL,
              failure_type TEXT,
              payload TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operation_logs (
              operation_id TEXT PRIMARY KEY,
              event_type TEXT NOT NULL,
              level TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_cards (
              card_id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_cases (
              case_id TEXT PRIMARY KEY,
              question TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()
