# Personal Multimodal RAG · Self-hosted Multimodal Evidence Platform

[中文说明](README.md) · **English**

[![CI](https://github.com/728792899-create/personal-multimodal-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/728792899-create/personal-multimodal-rag/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-0f766e.svg)](LICENSE)
[![Offline First](https://img.shields.io/badge/default-offline%20%2F%20zero--key-7c3aed.svg)](.env.example)

![PDF, URL, image and note evidence flowing through hybrid retrieval and a refusal gate](docs/assets/social-preview.png)

**A local-first multimodal RAG workbench where retrieval, refusal and citation quality stay inspectable.**

[Quick start](#zero-key-quick-start) · [Case study](docs/case-study.md) · [Architecture](docs/architecture.md) · [Evaluation](docs/evaluation-results.md) · [Security](docs/security-model.md) · [Full documentation](docs/README.md)

The project is a single-user Production Local RC rather than a chat UI wrapped around one model call. It ingests PDF, DOCX, Markdown, text, images and public URLs into isolated knowledge bases; combines BM25, vector and provenance-backed graph navigation; persists conversations; streams audited answers; refuses unsupported questions; and links every answer back to inspectable evidence.

**0.3 Multimodal Intelligence** adds a typed text/heading/image/table/equation/code intermediate representation, content-addressed assets, contextual enrichment, provenance-backed Graph-lite, 24-hour query images, precise element citations, and accessible graph inspection. Graph paths only navigate to local evidence chunks before RRF, MMR, reranking, refusal, and citation audit. Cooperative job cancellation now converges to a durable terminal state, and SQLite plus referenced objects can be exercised through a non-destructive isolated restore drill. The zero-download built-in parser and deterministic template enrichment remain the default; heavy parsers and vision providers are optional. See the [pinned RAG-Anything comparative review](docs/comparative-review-rag-anything.md) for the evidence and trade-offs.

The default path remains deterministic and offline: hash embeddings, an in-memory vector store and template answers require **no API key and make no paid API calls**.

**0.4.0-rc.1 Production Local** separates three supported paths: `demo` for zero-key review, `local-production` for SQLite/local objects/Chroma/Ollama, and `production` for PostgreSQL/pgvector, S3/MinIO, Redis Streams, ClamAV and a fail-closed real provider. It also adds Argon2id session authentication, CSRF, a server-resolved workspace boundary, transactional outbox/DLQ, checksum-verified SQLite migration, incremental directory/URL/RSS sources, guarded deletion candidates and citation-aware Markdown exports. The project deliberately does not claim “production-ready” before its real-corpus, recovery and 14-day soak gates are met.

## What reviewers can verify

| Product behavior | Trust mechanism | Engineering evidence |
| --- | --- | --- |
| File upload and guarded URL import | Evidence threshold and explicit refusal | FastAPI, Vue 3, Docker Compose |
| Ordinary and expert modes | Stage-by-stage retrieval Trace | pytest, Vitest and Playwright |
| Precise element citations and context | Citation and graph provenance audit | Fixed 100-case offline golden set |
| Feedback to evaluation draft | Request IDs, timeout, cancel and retry | Health checks and multi-lane CI |
| Durable local index jobs and source sync | Lease recovery, DLQ boundaries and restore drill | 136 backend / 19 frontend / 14 E2E tests |

![System map from ingestion to evidence-constrained answers and evaluation](docs/assets/system-overview.svg)

## Interface

| Workbench | Grounded answer | Mobile refusal |
| --- | --- | --- |
| ![Ordinary-mode workbench with knowledge and query panels](docs/screenshots/01-workbench-beta.png) | ![Answer citations and retrieval trace](docs/screenshots/02-grounded-trace.png) | ![Expert-mode refusal at a 390-pixel viewport](docs/screenshots/03-mobile-expert-refusal.png) |

The extended gallery also shows [URL ingestion](docs/screenshots/04-ingestion-url.png), [neighboring citation context](docs/screenshots/05-citation-context.png), [quality audit](docs/screenshots/06-quality-dashboard.png), [feedback-generated eval drafts](docs/screenshots/07-feedback-eval-draft.png), [retry after an API failure](docs/screenshots/08-error-retry.png), [multimodal query and persistent conversation state](docs/screenshots/09-multimodal-query-trace.jpg), [the accessible Graph evidence workbench](docs/screenshots/10-graph-evidence-workbench.jpg), [precise element citations](docs/screenshots/11-precise-element-citation.jpg), and [the 390-pixel expert layout](docs/screenshots/12-mobile-multimodal-expert.jpg).

## Zero-key quick start

Requirements: Python 3.11+ and Node.js 22+.

```bash
git clone https://github.com/728792899-create/personal-multimodal-rag.git
cd personal-multimodal-rag

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
npm ci
npm --prefix frontend ci
cp .env.example .env
npm run dev
```

In another terminal, load the repository's sanitized fixtures:

```bash
source .venv/bin/activate
npm run demo:bootstrap
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). The default environment uses:

```text
EMBEDDING_PROVIDER=mock
VECTOR_STORE=memory
ANSWER_PROVIDER=template
QUERY_REWRITE_PROVIDER=none
```

The Docker demo path is equally self-contained:

```bash
docker compose up --build --wait -d
npm run demo:bootstrap
```

## Runtime modes

| Mode | Data plane | Provider | Failure policy |
| --- | --- | --- | --- |
| `demo` | SQLite + local objects + memory vectors | mock + template | zero-key, auth may be disabled |
| `local-production` | SQLite + local objects + Chroma | Ollama `qwen3:8b`, `nomic-embed-text`, cross-encoder | no template fallback |
| `production` | PostgreSQL/pgvector + S3/MinIO + Redis Streams | Ollama or OpenAI-compatible | readiness fails when a required dependency is unavailable |

See the [Production Local runbook](docs/production-local.md) and [incremental source guide](docs/source-sync.md). The browser may select only server-configured directory aliases; empty or partial syncs cannot trigger mass deletion.

## Architecture and request lifecycle

![Browser, Nginx, middleware, domain routers, services and provider adapters in one request lifecycle](docs/assets/request-lifecycle.svg)

The Vue application is split into a page, domain components, the `useWorkbench` composable, and API modules. FastAPI keeps a stable composition root while document, retrieval and quality routes live in separate domain routers. The service layer owns ingestion, retrieval, answer generation and citation audit; provider adapters retain offline fallbacks.

Read the [architecture guide](docs/architecture.md), [code tour](docs/code-tour.md), [SQLite data model](docs/data-model.md), and [API reference](docs/api-reference.md) for implementation-level detail.

## Deterministic evaluation

![One-hundred-case offline scorecard covering retrieval, multimodal extraction and graph evidence](docs/assets/evaluation-scorecard.svg)

| Metric | Recorded result | CI minimum |
| --- | ---: | ---: |
| Recall@5 | 1.0000 | 0.90 |
| MRR | 0.9888 | 0.75 |
| First-citation accuracy | 0.9775 | 0.75 |
| Refusal accuracy | 1.0000 | 0.80 |
| Answer-acceptance accuracy | 1.0000 | 0.85 |
| Modality Recall@5 / table / caption / formula | all 1.0000 | 0.85 / 0.90 |
| Graph path precision / evidence coverage / multi-hop Recall@5 | all 1.0000 | 0.90 / 0.95 / 0.85 |

The set contains 100 sanitized cases: 89 answerable and 11 refusal cases, including 12 image, 12 table, 8 formula, 12 layout/OCR, 10 graph multi-hop, and 6 conflict/refusal additions. These numbers are regression signals for fixed repository fixtures—not a claim about open-domain production quality. See [evaluation results and caveats](docs/evaluation-results.md).

Run all acceptance checks with offline providers enforced:

```bash
npm run verify
```

Or run `npm test`, `npm run lint:docs`, `npm run lint:secrets`, `npm run build`, `npm run test:demo`, `npm run eval:retrieval`, `npm run test:restore-drill`, and `npm run test:e2e` separately.

## Security and production boundary

![Trust boundaries between the browser, API, untrusted input, providers and storage](docs/assets/security-boundaries.svg)

Implemented controls cover upload type/size/signature checks, SSRF-aware URL validation across redirects, Argon2id session authentication, HttpOnly/Secure/SameSite cookies, CSRF, login rate limiting, timeouts, terminal cooperative cancellation, request IDs and sensitive-log redaction. Production object ingestion uses staged content-addressed keys and an optional ClamAV gate. `scripts/verify_local_restore.py` creates an isolated SQLite snapshot and checks integrity, foreign keys, schema, safe object paths, byte sizes and SHA-256 without changing business rows in the input database.

This repository does **not** claim multi-tenant isolation or a completed 1.0 production gate. The default workspace, owner, session and membership boundary is server-resolved, but 0.4 remains a single-admin deployment. OIDC/RBAC, HA, Kubernetes and multi-tenant authorization are deferred. The boundaries and migration steps are explicit in the [Production Local runbook](docs/production-local.md), [security model](docs/security-model.md), and [production adapter plan](docs/production-adapters.md).

## License

[MIT](LICENSE). For contributions and responsible disclosure, see [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
