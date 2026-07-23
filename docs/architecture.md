# 架构说明

![系统全景：输入、入库、检索、回答和质量闭环](assets/system-overview.svg)

这张图用于快速理解系统边界；下面的 Mermaid 图展示更接近代码模块的依赖关系。默认离线链路与可选生产 adapter 使用同一套领域接口。

![一次请求经过 Nginx、中间件、领域路由、服务和 provider 的生命周期](assets/request-lifecycle.svg)

## 1. 系统分层

```mermaid
flowchart TB
  subgraph UI["交互层"]
    WORKBENCH["Vue 3 / TypeScript 工作台"]
    MODES["普通模式 / 专家模式"]
    QUERYIMG["临时图片提问"]
  end

  subgraph API["接口与编排层"]
    FASTAPI["FastAPI Routes"]
    WORKER["Lifespan Local Worker"]
    PROCESSOR["Document Processor"]
    ENGINE["RAG Engine"]
    TOOLS["Knowledge Tools / Metrics / Eval"]
    QAS["Query Asset Service"]
  end

  subgraph RETRIEVAL["检索与可信度层"]
    BM25["BM25 Index"]
    VECTOR["Vector Store"]
    HYBRID["Hybrid Retriever"]
    RERANK["MMR + Reranker"]
    GATE["No-answer Gate"]
    AUDIT["Citation Audit"]
    GRAPH["Provenance Graph-lite"]
    RRF["Weighted RRF"]
  end

  subgraph ADAPTERS["可替换适配层"]
    EMBED["Mock / Local / OpenAI-compatible Embedding"]
    STORE["Memory / Chroma / pgvector"]
    ANSWER["Template / Responses / Chat / Ollama"]
  end

  subgraph PERSIST["持久化层"]
    REGISTRY["SQLite KB / Sessions / Jobs"]
    UPLOADS["Local Upload Files"]
  end

  WORKBENCH --> FASTAPI
  QUERYIMG --> QAS --> FASTAPI
  MODES --> WORKBENCH
  FASTAPI --> PROCESSOR
  FASTAPI --> WORKER
  WORKER --> PROCESSOR
  FASTAPI --> ENGINE
  FASTAPI --> TOOLS
  PROCESSOR --> REGISTRY
  PROCESSOR --> UPLOADS
  PROCESSOR --> BM25
  PROCESSOR --> GRAPH
  PROCESSOR --> EMBED
  EMBED --> STORE
  STORE --> VECTOR
  ENGINE --> HYBRID
  GRAPH --> RRF
  HYBRID --> RRF
  BM25 --> HYBRID
  VECTOR --> HYBRID
  RRF --> RERANK --> GATE
  GATE --> ANSWER --> AUDIT --> FASTAPI
```

## 关键模块

| 模块 | 文件 | 职责 |
| --- | --- | --- |
| 文档解析 | `backend/app/services/document_processor.py` | PDF/DOCX/文本/OCR、chunk 切分、metadata |
| 多模态 enrichment | `backend/app/services/{context_window,multimodal_enrichment}.py` | 有界相邻上下文、确定性/视觉结构化描述与缓存 |
| 查询图片 | `backend/app/services/query_assets.py` | 签名/像素/大小校验、OCR/视觉增强、KB 边界与 TTL 清理 |
| Graph-lite | `backend/app/services/{graph_store,graph_adapters}.py` | provenance 节点/边、路径、KB 隔离和 LightRAG 导航白名单 |
| 韧性执行 | `backend/app/services/resilience.py` | 超时类错误重试、指数退避、抖动与熔断 |
| 入库任务 | `backend/app/services/ingestion_jobs.py` | SQLite claim、租约、重试、取消、阶段进度 |
| URL 导入 | `backend/app/services/url_importer.py` | 抓取网页、清洗正文、生成文档 |
| 检索器 | `backend/app/services/retriever.py` | BM25、向量召回、MMR、rerank 前候选 |
| RAG 引擎 | `backend/app/services/rag_engine.py` | 问答编排、拒答、trace、parent context |
| 引用审计 | `backend/app/services/citation_audit.py` | 引用覆盖率、unsupported claims |
| 知识工具 | `backend/app/services/knowledge_tools.py` | 改写、知识卡片、缺口分析 |
| 系统指标 | `backend/app/services/system_metrics.py` | 文档质量、置信度、反馈和日志统计 |
| 前端页面 | `frontend/src/pages/WorkbenchPage.vue` | 普通/专家模式与三栏信息架构 |
| 前端状态 | `frontend/src/composables/useWorkbench.ts` | 请求取消、重试、状态与领域动作 |
| 领域状态 | `frontend/src/composables/use{KnowledgeBases,IngestionJobs,Conversations,ProviderStatus,MultimodalQuery,DocumentViewer,GraphTrace,QualityAudit}.ts` | KB、任务、SSE、图片、元素、Graph 与审计 |
| 前端 API | `frontend/src/api/` | 超时/错误 client 与 documents/retrieval/quality API |
| 后端路由 | `backend/app/api/routers/` | documents/retrieval/quality 领域路由 |

更适合按请求阅读的文件级入口见[代码导览](code-tour.md)。

## 2. 资料入库与安全边界

```mermaid
flowchart LR
  subgraph INPUT["输入"]
    FILE["PDF / DOCX / Markdown / Text / Image"]
    URL["Web URL"]
  end

  FILE --> FGUARD["扩展名 / 大小 / 空文件 / Magic bytes / 文件名"]
  URL --> UGUARD["地址 / 重定向 / DNS / 类型 / 大小 / 超时"]
  FGUARD --> JOB["SQLite Job / Idempotency"]
  JOB --> PARSE["文本/DOCX 解析 / 可选 OCR"]
  UGUARD --> PARSE
  PARSE --> HASH["SHA-256 去重"]
  HASH --> CHUNK["Chunk + Overlap + Metadata"]
  CHUNK --> QUALITY["质量评分 / 索引状态"]
  CHUNK --> BM25["BM25"]
  CHUNK --> EMBED["Embedding Provider"]
  EMBED --> VECTOR["Vector Store"]
  QUALITY --> REGISTRY["SQLite Registry"]
  PARSE -. "失败时清理临时文件" .-> CLEANUP["Cleanup"]
```

URL 导入默认拒绝回环、内网、链路本地和特殊地址。校验不只发生在初始 URL，还覆盖重定向与最终响应，避免通过跳转绕过 SSRF 防线。

![不可信文件、URL、外部 provider 和本地存储之间的信任边界](assets/security-boundaries.svg)

## 3. 问答检索时序

![十阶段多模态与 Graph 检索管线](assets/retrieval-pipeline.svg)

```mermaid
sequenceDiagram
  participant U as 用户
  participant W as Vue 工作台
  participant C as Conversation API
  participant E as RAG Engine
  participant R as Hybrid Retriever
  participant GR as Graph-lite
  participant G as Answer Generator
  participant A as Citation Audit

  U->>W: 提交问题、文档范围与检索参数
  W->>C: POST messages:stream
  C->>C: 保存 user/streaming message + 最近六轮
  C->>E: 问题 + KB scope
  E->>E: Normalize / Intent / Query Rewrite
  E->>R: BM25 与向量并行召回
  opt strategy=hybrid_graph 或 auto 门控成立
    R->>GR: entity seed + KB scope + max hops
    GR-->>R: provenance-backed path + element IDs
    R->>R: Weighted RRF
  end
  R->>R: Dedup / Parent Context / MMR / Rerank
  R-->>E: Evidence + Retrieval Trace
  alt 证据不足
    E-->>C: refusal
    C-->>W: refusal → done
  else 证据满足门槛
    E->>G: 问题 + 受约束证据
    G-->>E: 带引用回答
    E->>A: 回答与实际引用片段
    A-->>E: 覆盖率、Grounding 与 Unsupported Claims
    E-->>C: answer.delta* → answer.completed
    C-->>W: 最终引用、Trace 与可信度审计 → done
  end
```

## 4. 元素、enrichment 与图谱证据流

```mermaid
flowchart LR
  SOURCE["受控原件 / URL 正文"] --> PARSER["Builtin 或隔离 Parser"]
  PARSER --> IR["DocumentElement IR"]
  IR --> CONTEXT["Bounded Context Window"]
  CONTEXT --> ENRICH["Template / Vision Enrichment"]
  ENRICH --> CACHE["Versioned Enrichment Cache"]
  ENRICH --> CHUNK["Element-derived Chunks"]
  IR --> PROVENANCE["Evidence Element + Span"]
  PROVENANCE --> GRAPH["Native Graph-lite"]
  GRAPH --> PATH["Seed / Path / Evidence IDs"]
  CHUNK --> HYBRID["BM25 + Vector"]
  PATH --> RRF["Weighted RRF k=60"]
  HYBRID --> RRF
  RRF --> MMR["Parent Context → MMR → Rerank"]
  MMR --> GATE["Refusal + Citation Gate"]
```

这条链有两个硬边界：Provider 关系必须在原元素中找到 `evidence_span`；图谱输出必须先映射回本地 chunk 才能进入排序。图边本身不能满足回答门槛。

## 5. 反馈与评测闭环

![反馈到 CI 门禁](assets/evaluation-loop.svg)

```mermaid
flowchart LR
  A["用户提问"] --> B["检索与回答"]
  B --> C["引用审计"]
  C --> D["用户反馈"]
  D --> E["Eval Draft"]
  E --> F["运行评测"]
  F --> G["调整检索策略"]
  G --> B
```

## 6. Provider 与降级策略

```mermaid
flowchart LR
  CFG["环境变量配置"] --> EMB["Embedding Adapter"]
  CFG --> VS["Vector Store Adapter"]
  CFG --> RW["Query Rewrite Adapter"]
  CFG --> AG["Answer Adapter"]
  CFG --> ME["Multimodal Enrichment Adapter"]

  EMB -->|"默认离线"| MOCK["Hash / Mock"]
  EMB -->|"可选"| REAL_EMB["Sentence Transformer / OpenAI / Ollama"]
  VS --> MEMORY["Memory"]
  VS --> CHROMA["Chroma"]
  VS --> PG["pgvector"]
  RW -->|"未配置或失败"| NOOP["No-op Rewrite"]
  AG -->|"local/test 显式允许"| TEMPLATE["Template Fallback"]
  AG -->|"可选"| RESPONSES["Responses / Chat / Ollama"]
  ME -->|"默认离线"| TEMPLATE_ENRICH["Template + OCR/Table/Formula"]
  ME -->|"可选"| VISION["Responses / Compatible Vision / Ollama Vision"]
```

默认演示链路完全离线，目的是让代码审查和面试演示可复现；真实模型、持久向量库和 cross-encoder 属于可替换增强项，不能把默认 hash embedding 的效果描述成生产检索质量。

## 7. 启动恢复与容器边界

![部署演进模式](assets/deployment-modes.svg)

SQLite 保存文档、知识库、会话、消息与任务。启动时恢复过期租约，再加载 registry 并验证 embedding dimension/model/index version；只为兼容且缺失的文档重建索引。不兼容记录进入 `needs_rebuild`，不会混入当前检索。

![当前 SQLite 表、vector chunk 和生产 workspace 迁移边界](assets/data-model.svg)

字段、删除语义和迁移顺序见[SQLite 数据模型](data-model.md)。

Compose 的 Nginx 只暴露静态前端与 `/api` 代理，FastAPI `/ready` 返回当前 provider。前后端 healthcheck 与 `depends_on: condition=service_healthy` 防止前端在后端未就绪时被标记为整体可用。

## 设计取舍

- 没有直接依赖 LangChain，是为了展示 RAG 核心链路和工程拆分能力。
- 默认 mock embedding 可离线运行，真实演示可切换 local/OpenAI-compatible embedding。
- 普通模式隐藏复杂参数，专家模式展示 trace 和调参入口。
- Citation audit 先采用规则可解释实现，后续可升级为 NLI/LLM-as-judge。

## 延伸阅读

- [产品巡游](product-tour.md)：从用户动作理解信息架构与状态。
- [检索与可信回答](retrieval-explained.md)：阶段、分数、拒答和诊断。
- [API 使用指南](api-reference.md)：端点、payload 与错误语义。
- [配置指南](configuration.md)：provider、store、门槛与安全配置。
- [生产适配方案](production-adapters.md)：workspace、任务、pgvector 与对象存储。
- [安全威胁模型](security-model.md)：信任边界、已实现控制与剩余风险。
