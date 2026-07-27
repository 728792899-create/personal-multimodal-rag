# Personal Multimodal RAG · Self-hosted Multimodal Evidence Platform

[中文说明](README.md) · **English**

[![持续集成](https://img.shields.io/badge/%E6%8C%81%E7%BB%AD%E9%9B%86%E6%88%90-%E6%9F%A5%E7%9C%8B%E5%B7%A5%E4%BD%9C%E6%B5%81-0f766e.svg)](https://github.com/728792899-create/personal-multimodal-rag/actions/workflows/ci.yml)
[![许可证：MIT](https://img.shields.io/badge/%E8%AE%B8%E5%8F%AF%E8%AF%81-MIT-0f766e.svg)](LICENSE)
[![离线优先](https://img.shields.io/badge/%E9%BB%98%E8%AE%A4-%E7%A6%BB%E7%BA%BF%20%2F%20%E9%9B%B6%E5%AF%86%E9%92%A5-7c3aed.svg)](.env.example)

<!-- Visual assets are pinned to an immutable commit to avoid short-lived GitHub raw/main cache reuse. Update this revision whenever a visual changes. -->

![PDF, URL, image and note evidence flowing through hybrid retrieval and a refusal gate](https://raw.githubusercontent.com/728792899-create/personal-multimodal-rag/325861226185384a9a4b1803d0224e0eaad98b41/docs/assets/social-preview.png)

**A local-first multimodal RAG workbench where retrieval, refusal and citation quality stay inspectable.**

[Quick start](#zero-key-quick-start) · [Case study](docs/case-study.md) · [Production validation](docs/production-validation.md) · [Architecture](docs/architecture.md) · [Evaluation](docs/evaluation-results.md) · [Security](docs/security-model.md)

The project is a single-user Production Local RC rather than a chat UI wrapped around one model call. It ingests PDF, DOCX, Markdown, text, images and public URLs into isolated knowledge bases; combines BM25, vector and provenance-backed graph navigation; persists conversations; streams audited answers; refuses unsupported questions; and links every answer back to inspectable evidence.

**0.3 Multimodal Intelligence** adds a typed text/heading/image/table/equation/code intermediate representation, content-addressed assets, contextual enrichment, provenance-backed Graph-lite, 24-hour query images, precise element citations, and accessible graph inspection. Graph paths only navigate to local evidence chunks before RRF, MMR, reranking, refusal, and citation audit. Cooperative job cancellation now converges to a durable terminal state, and SQLite plus referenced objects can be exercised through a non-destructive isolated restore drill. The zero-download built-in parser and deterministic template enrichment remain the default; heavy parsers and vision providers are optional. See the [pinned RAG-Anything comparative review](docs/comparative-review-rag-anything.md) for the evidence and trade-offs.

The default path remains deterministic and offline: hash embeddings, an in-memory vector store and template answers require **no API key and make no paid API calls**.

**0.4.0-rc.1 Production Local** separates three supported paths: `demo` for zero-key review, `local-production` for SQLite/local objects/Chroma/Ollama, and `production` for PostgreSQL/pgvector, S3/MinIO, Redis Streams, ClamAV and a fail-closed real provider. It also adds Argon2id session authentication, CSRF, a server-resolved workspace boundary, transactional outbox/DLQ, checksum-verified SQLite migration, incremental directory/URL/RSS sources, guarded deletion candidates and citation-aware Markdown exports. The project deliberately does not claim “production-ready” before its real-corpus, recovery and 14-day soak gates are met.

The private 2026-07-23 production run indexed **200 non-fixture documents from 21 licensed source groups into 5,159 768-dimensional vectors** and passed destructive PostgreSQL/pgvector/MinIO recovery plus five API/worker/Redis/PostgreSQL/MinIO fault scenarios. A real MinerU job passed. Ollama embeddings passed, while all three `qwen3:8b` generation contracts timed out at 180 seconds on this host. The non-backfillable soak chain has honestly retained four host/container-runtime gaps and reset after each excessive interval; as of 2026-07-26 its longest continuous window is 81,984 seconds and the current window started at `2026-07-26T04:57:18Z`. Human review remains 0/200, attested real questions 0/100, and Sentry has no DSN. The release therefore remains an RC. See the [production validation runbook](docs/production-validation.md).

## What reviewers can verify

| Product behavior | Trust mechanism | Engineering evidence |
| --- | --- | --- |
| File upload and guarded URL import | Evidence threshold and explicit refusal | FastAPI, Vue 3, Docker Compose |
| Simple and debug (expert) modes | Stage-by-stage retrieval Trace | pytest, Vitest and Playwright |
| Precise element citations and context | Citation and graph provenance audit | Fixed 100-case offline golden set |
| Feedback to evaluation draft | Request IDs, timeout, cancel and retry | Health checks and multi-lane CI |
| Durable local index jobs and source sync | Lease recovery, DLQ boundaries and restore drill | 179 backend passes, 3 skipped + 2 PostgreSQL contracts / 27 frontend / 14 E2E |

![System map from ingestion to evidence-constrained answers and evaluation](https://raw.githubusercontent.com/728792899-create/personal-multimodal-rag/325861226185384a9a4b1803d0224e0eaad98b41/docs/assets/system-overview.svg)

## Interface

![Production Local sign-in boundary](https://raw.githubusercontent.com/728792899-create/personal-multimodal-rag/325861226185384a9a4b1803d0224e0eaad98b41/docs/screenshots/13-evidence-ledger-login.png)

The default experience is a **question-first** single canvas. Everyday users see the prompt, answer, and sources; file upload, library management, and retrieval traces live in on-demand drawers. `Cmd/Ctrl + K` focuses the prompt, `Esc` closes a drawer, and BM25, vector, Graph, MMR, and rerank controls only appear in debug mode.

| Question-first home | Retrieval debugging | 390-pixel layout |
| --- | --- | --- |
| ![Minimal multimodal knowledge-base question page](https://raw.githubusercontent.com/728792899-create/personal-multimodal-rag/325861226185384a9a4b1803d0224e0eaad98b41/docs/screenshots/01-workbench-beta.png) | ![On-demand advanced retrieval parameters](https://raw.githubusercontent.com/728792899-create/personal-multimodal-rag/325861226185384a9a4b1803d0224e0eaad98b41/docs/screenshots/15-question-first-debug.png) | ![Question page and bottom shortcuts at a 390-pixel viewport](https://raw.githubusercontent.com/728792899-create/personal-multimodal-rag/325861226185384a9a4b1803d0224e0eaad98b41/docs/screenshots/14-evidence-ledger-mobile.png) |

![Search-only FastAPI reverse-proxy result with five relevant, inspectable sources](https://raw.githubusercontent.com/728792899-create/personal-multimodal-rag/325861226185384a9a4b1803d0224e0eaad98b41/docs/screenshots/16-question-first-sources.png)

Simple mode hides provider internals, retrieval weights, and raw scores. It leads with the result and sources; selecting a source opens the evidence and debugging drawer.

### Key workflows

The library drawer owns file upload, URL import, and index status. The source drawer provides neighboring context, quality and citation audits. Feedback creates evaluation drafts, while failure states retain request IDs and retry actions. Multimodal image queries, Graph evidence navigation, and precise element citations all live in the current interface's on-demand drawers rather than mixing historical UI into the project homepage.

See the [case study](docs/case-study.md), [product tour](docs/product-tour.md), and [screenshot verification index](docs/screenshots/README.md) for the full interaction walkthrough.

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

Production URL and feed retrieval is delegated to a credential-free, read-only
fetch worker. Every redirect is revalidated, the socket is pinned to a
previously validated public IP, and response size/time limits are enforced.

## Architecture and request lifecycle

![Browser, Nginx, middleware, domain routers, services and provider adapters in one request lifecycle](https://raw.githubusercontent.com/728792899-create/personal-multimodal-rag/325861226185384a9a4b1803d0224e0eaad98b41/docs/assets/request-lifecycle.svg)

The Vue application is split into a page, domain components, the `useWorkbench` composable, and API modules. FastAPI keeps a stable composition root while document, retrieval and quality routes live in separate domain routers. The service layer owns ingestion, retrieval, answer generation and citation audit; provider adapters retain offline fallbacks.

Read the [architecture guide](docs/architecture.md), [code tour](docs/code-tour.md), [SQLite data model](docs/data-model.md), and [API reference](docs/api-reference.md) for implementation-level detail.

## Deterministic evaluation

![One-hundred-case offline scorecard covering retrieval, multimodal extraction and graph evidence](https://raw.githubusercontent.com/728792899-create/personal-multimodal-rag/325861226185384a9a4b1803d0224e0eaad98b41/docs/assets/evaluation-scorecard.svg)

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

Production contracts are separate from fixture quality:

```bash
npm run verify:production   # fail-closed Compose, auth, queue, object and backup contracts
npm run benchmark:real      # requires a private operator-supplied evidence manifest
npm run chaos:compose       # safe dry-run unless an explicit destructive confirmation is supplied
npm run backup:production
npm run restore:production  # verifies only unless --confirm RESTORE is supplied to the script
```

The current 1.0 status is intentionally blocked until the licensed real corpus,
200 non-fixture documents, 200 annotations, 100 real questions, full restore,
14-day soak and quality thresholds have evidence. See the
[1.0 release-evidence report](docs/release-evidence-1.0.md); the same gate list
is exposed by `GET /api/system/readiness-report`.

## Security and production boundary

![Trust boundaries between the browser, API, untrusted input, providers and storage](https://raw.githubusercontent.com/728792899-create/personal-multimodal-rag/325861226185384a9a4b1803d0224e0eaad98b41/docs/assets/security-boundaries.svg)

Implemented controls cover upload type/size/signature checks, SSRF-aware URL validation across redirects, Argon2id session authentication, HttpOnly/Secure/SameSite cookies, CSRF, login rate limiting, timeouts, terminal cooperative cancellation, request IDs and sensitive-log redaction. Production object ingestion uses staged content-addressed keys and an optional ClamAV gate. `scripts/verify_local_restore.py` creates an isolated SQLite snapshot and checks integrity, foreign keys, schema, safe object paths, byte sizes and SHA-256 without changing business rows in the input database.

`/metrics` exposes bounded Prometheus labels for HTTP, retrieval, first-token,
provider, citation, queue, DLQ and source-sync behavior. An optional Compose
profile provisions Prometheus, an OpenTelemetry Collector and Grafana. Sentry
and OTLP exporters are opt-in, and scrubbers remove bodies, questions,
credentials, cookies and private URL queries from telemetry.

Security automation adds CodeQL, dependency audit, Trivy and an SPDX SBOM.
Release images are produced only by the release workflow with provenance,
GitHub build attestation and keyless Cosign signing.

This repository does **not** claim multi-tenant isolation or a completed 1.0 production gate. The default workspace, owner, session and membership boundary is server-resolved, but 0.4 remains a single-admin deployment. OIDC/RBAC, HA, Kubernetes and multi-tenant authorization are deferred. The boundaries and migration steps are explicit in the [Production Local runbook](docs/production-local.md), [security model](docs/security-model.md), and [production adapter plan](docs/production-adapters.md).

## License

[MIT](LICENSE). For contributions and responsible disclosure, see [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
