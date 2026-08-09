CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_chunks_v2_initial (
  chunk_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  knowledge_base_id TEXT NOT NULL DEFAULT 'default',
  modality TEXT NOT NULL DEFAULT 'text',
  file_name TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  page_number INTEGER,
  heading_path JSONB,
  metadata JSONB,
  text TEXT NOT NULL,
  embedding_text TEXT NOT NULL,
  content_hash TEXT NOT NULL DEFAULT '',
  token_count INTEGER NOT NULL DEFAULT 0,
  embedding vector(1536) NOT NULL
);

CREATE INDEX IF NOT EXISTS rag_chunks_v2_initial_document_id_idx
  ON rag_chunks_v2_initial(document_id);
CREATE INDEX IF NOT EXISTS rag_chunks_v2_initial_kb_modality_idx
  ON rag_chunks_v2_initial(knowledge_base_id, modality);
CREATE INDEX IF NOT EXISTS rag_chunks_v2_initial_kb_document_idx
  ON rag_chunks_v2_initial(knowledge_base_id, document_id);
CREATE INDEX IF NOT EXISTS rag_chunks_v2_initial_embedding_hnsw_idx
  ON rag_chunks_v2_initial
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 128);

CREATE TABLE IF NOT EXISTS rag_chunks_v2_initial_postings (
  term TEXT NOT NULL,
  chunk_id TEXT NOT NULL REFERENCES rag_chunks_v2_initial(chunk_id)
    ON DELETE CASCADE,
  document_id TEXT NOT NULL,
  knowledge_base_id TEXT NOT NULL,
  modality TEXT NOT NULL,
  term_frequency INTEGER NOT NULL,
  chunk_length INTEGER NOT NULL,
  PRIMARY KEY (term, chunk_id)
);

CREATE INDEX IF NOT EXISTS rag_chunks_v2_initial_postings_chunk_idx
  ON rag_chunks_v2_initial_postings(chunk_id);
CREATE INDEX IF NOT EXISTS rag_chunks_v2_initial_postings_kb_term_idx
  ON rag_chunks_v2_initial_postings(knowledge_base_id, term);

CREATE TABLE IF NOT EXISTS rag_index_versions (
  index_id TEXT PRIMARY KEY,
  table_name TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (
    status IN ('candidate', 'stable', 'active', 'rollback', 'failed')
  ),
  embedding_provider TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  embedding_dimension INTEGER NOT NULL,
  parser_version TEXT NOT NULL,
  chunker_version TEXT NOT NULL,
  source_index_id TEXT NOT NULL DEFAULT '',
  validation TEXT NOT NULL DEFAULT '{}',
  metrics TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  activated_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_rag_index_versions_status
  ON rag_index_versions(status);

CREATE TABLE IF NOT EXISTS rag_index_state (
  workspace_id TEXT PRIMARY KEY,
  active_index_id TEXT NOT NULL DEFAULT '',
  previous_index_id TEXT NOT NULL DEFAULT '',
  generation BIGINT NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

INSERT INTO rag_index_state
  (workspace_id, active_index_id, previous_index_id, generation, updated_at)
VALUES ('default', '', '', 0, CURRENT_TIMESTAMP::TEXT)
ON CONFLICT (workspace_id) DO NOTHING;
