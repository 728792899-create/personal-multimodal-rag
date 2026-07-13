# 架构说明

## 1. 系统分层

```mermaid
flowchart TB
  subgraph UI["交互层"]
    WORKBENCH["Vue 3 / TypeScript 工作台"]
    MODES["普通模式 / 专家模式"]
  end

  subgraph API["接口与编排层"]
    FASTAPI["FastAPI Routes"]
    PROCESSOR["Document Processor"]
    ENGINE["RAG Engine"]
    TOOLS["Knowledge Tools / Metrics / Eval"]
  end

  subgraph RETRIEVAL["检索与可信度层"]
    BM25["BM25 Index"]
    VECTOR["Vector Store"]
    HYBRID["Hybrid Retriever"]
    RERANK["MMR + Reranker"]
    GATE["No-answer Gate"]
    AUDIT["Citation Audit"]
  end

  subgraph ADAPTERS["可替换适配层"]
    EMBED["Mock / Local / OpenAI-compatible Embedding"]
    STORE["Memory / Chroma / pgvector"]
    ANSWER["Template / Responses Answer"]
  end

  subgraph PERSIST["持久化层"]
    REGISTRY["SQLite Document Registry"]
    UPLOADS["Local Upload Files"]
  end

  WORKBENCH --> FASTAPI
  MODES --> WORKBENCH
  FASTAPI --> PROCESSOR
  FASTAPI --> ENGINE
  FASTAPI --> TOOLS
  PROCESSOR --> REGISTRY
  PROCESSOR --> UPLOADS
  PROCESSOR --> BM25
  PROCESSOR --> EMBED
  EMBED --> STORE
  STORE --> VECTOR
  ENGINE --> HYBRID
  BM25 --> HYBRID
  VECTOR --> HYBRID
  HYBRID --> RERANK --> GATE
  GATE --> ANSWER --> AUDIT --> FASTAPI
```

## 关键模块

| 模块 | 文件 | 职责 |
| --- | --- | --- |
| 文档解析 | `backend/app/services/document_processor.py` | 文件/文本解析、chunk 切分、metadata |
| URL 导入 | `backend/app/services/url_importer.py` | 抓取网页、清洗正文、生成文档 |
| 检索器 | `backend/app/services/retriever.py` | BM25、向量召回、MMR、rerank 前候选 |
| RAG 引擎 | `backend/app/services/rag_engine.py` | 问答编排、拒答、trace、parent context |
| 引用审计 | `backend/app/services/citation_audit.py` | 引用覆盖率、unsupported claims |
| 知识工具 | `backend/app/services/knowledge_tools.py` | 改写、知识卡片、缺口分析 |
| 系统指标 | `backend/app/services/system_metrics.py` | 文档质量、置信度、反馈和日志统计 |
| 前端工作台 | `frontend/src/App.vue` | 普通/专家模式、引用、评测、卡片 |

## 2. 资料入库与安全边界

```mermaid
flowchart LR
  subgraph INPUT["输入"]
    FILE["PDF / Markdown / Text / Image"]
    URL["Web URL"]
  end

  FILE --> FGUARD["扩展名白名单 / 20 MB 上限 / 文件名清理"]
  URL --> UGUARD["初始地址 / 每次重定向 / 最终地址校验"]
  FGUARD --> PARSE["文本解析 / 可选 OCR"]
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

## 3. 问答检索时序

```mermaid
sequenceDiagram
  participant U as 用户
  participant W as Vue 工作台
  participant E as RAG Engine
  participant R as Hybrid Retriever
  participant G as Answer Generator
  participant A as Citation Audit

  U->>W: 提交问题、文档范围与检索参数
  W->>E: POST /api/ask
  E->>E: Normalize / Intent / Query Rewrite
  E->>R: BM25 与向量并行召回
  R->>R: Score Fusion / Dedup / MMR / Rerank
  R-->>E: Evidence + Retrieval Trace
  alt 证据不足
    E-->>W: 拒答、资料缺口与修复建议
  else 证据满足门槛
    E->>G: 问题 + 受约束证据
    G-->>E: 带引用回答
    E->>A: 回答与实际引用片段
    A-->>E: 覆盖率、Grounding 与 Unsupported Claims
    E-->>W: 回答、引用、Trace 与可信度审计
  end
```

## 4. 反馈与评测闭环

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

## 5. Provider 与降级策略

```mermaid
flowchart LR
  CFG["环境变量配置"] --> EMB["Embedding Adapter"]
  CFG --> VS["Vector Store Adapter"]
  CFG --> RW["Query Rewrite Adapter"]
  CFG --> AG["Answer Adapter"]

  EMB -->|"默认离线"| MOCK["Hash / Mock"]
  EMB -->|"可选"| REAL_EMB["Local Sentence Transformer / OpenAI-compatible"]
  VS --> MEMORY["Memory"]
  VS --> CHROMA["Chroma"]
  VS --> PG["pgvector"]
  RW -->|"未配置或失败"| NOOP["No-op Rewrite"]
  AG -->|"未配置或初始化失败"| TEMPLATE["Template Answer"]
  AG -->|"可选"| RESPONSES["Responses-compatible Model"]
```

默认演示链路完全离线，目的是让代码审查和面试演示可复现；真实模型、持久向量库和 cross-encoder 属于可替换增强项，不能把默认 hash embedding 的效果描述成生产检索质量。

## 设计取舍

- 没有直接依赖 LangChain，是为了展示 RAG 核心链路和工程拆分能力。
- 默认 mock embedding 可离线运行，真实演示可切换 local/OpenAI-compatible embedding。
- 普通模式隐藏复杂参数，专家模式展示 trace 和调参入口。
- Citation audit 先采用规则可解释实现，后续可升级为 NLI/LLM-as-judge。
