# 架构说明

![系统全景：输入、入库、检索、回答和质量闭环](assets/system-overview.svg)

这张图用于快速理解系统边界；下面的 Mermaid 图展示更接近代码模块的依赖关系。默认离线链路与可选生产适配器使用同一套领域接口。

![一次请求经过 Nginx、中间件、领域路由、服务和模型提供方的生命周期](assets/request-lifecycle.svg)

## 1. 系统分层

```mermaid
flowchart TB
  subgraph UI["交互层"]
    WORKBENCH["Vue 3 / TypeScript 工作台"]
    MODES["普通模式 / 专家模式"]
    QUERYIMG["临时图片提问"]
  end

  subgraph API["接口与编排层"]
    FASTAPI["FastAPI 路由"]
    WORKER["生命周期本地工作进程"]
    PROCESSOR["文档处理器"]
    ENGINE["RAG 引擎"]
    TOOLS["知识工具 / 指标 / 评测"]
    QAS["查询图片服务"]
  end

  subgraph RETRIEVAL["检索与可信度层"]
    BM25["BM25 索引"]
    VECTOR["向量库"]
    HYBRID["混合检索器"]
    RERANK["MMR + 重排器"]
    GATE["无答案门"]
    AUDIT["引用审计"]
    GRAPH["带来源的轻量图谱"]
    RRF["加权 RRF"]
  end

  subgraph ADAPTERS["可替换适配层"]
    EMBED["模拟 / 本地 / OpenAI 兼容嵌入"]
    STORE["内存 / Chroma / pgvector"]
    ANSWER["模板 / Responses / 聊天 / Ollama"]
  end

  subgraph PERSIST["持久化层"]
    REGISTRY["SQLite 知识库 / 会话 / 任务"]
    UPLOADS["本地上传文件"]
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
| 文档解析 | `backend/app/services/document_processor.py` | PDF/DOCX/文本/OCR、分块切分、元数据 |
| 多模态增强 | `backend/app/services/{context_window,multimodal_enrichment}.py` | 有界相邻上下文、确定性/视觉结构化描述与缓存 |
| 查询图片 | `backend/app/services/query_assets.py` | 签名/像素/大小校验、OCR/视觉增强、知识库边界与 TTL 清理 |
| 轻量图谱 | `backend/app/services/{graph_store,graph_adapters}.py` | 来源节点/边、路径、知识库隔离和 LightRAG 导航白名单 |
| 韧性执行 | `backend/app/services/resilience.py` | 超时类错误重试、指数退避、抖动与熔断 |
| 入库任务 | `backend/app/services/ingestion_jobs.py` | SQLite 认领、租约、重试、取消、阶段进度 |
| URL 导入 | `backend/app/services/url_importer.py` | 抓取网页、清洗正文、生成文档 |
| 检索器 | `backend/app/services/retriever.py` | BM25、向量召回、MMR、重排前候选 |
| RAG 引擎 | `backend/app/services/rag_engine.py` | 问答编排、拒答、检索追踪、父级上下文 |
| 引用审计 | `backend/app/services/citation_audit.py` | 引用覆盖率、无支撑主张 |
| 知识工具 | `backend/app/services/knowledge_tools.py` | 改写、知识卡片、缺口分析 |
| 系统指标 | `backend/app/services/system_metrics.py` | 文档质量、置信度、反馈和日志统计 |
| 前端页面 | `frontend/src/pages/WorkbenchPage.vue` | 问题优先画布、按需抽屉与普通/调试模式 |
| 前端状态 | `frontend/src/composables/useWorkbench.ts` | 请求取消、重试、状态与领域动作 |
| 领域状态 | `frontend/src/composables/use{KnowledgeBases,IngestionJobs,Conversations,ProviderStatus,MultimodalQuery,DocumentViewer,GraphTrace,QualityAudit}.ts` | 知识库、任务、SSE、图片、元素、图谱与审计 |
| 前端 API | `frontend/src/api/` | 超时/错误客户端与文档/检索/质量 API |
| 后端路由 | `backend/app/api/routers/` | 文档/检索/质量领域路由 |

更适合按请求阅读的文件级入口见[代码导览](code-tour.md)。

## 2. 资料入库与安全边界

```mermaid
flowchart LR
  subgraph INPUT["输入"]
    FILE["PDF / DOCX / Markdown / 文本 / 图片"]
    URL["网页 URL"]
  end

  FILE --> FGUARD["扩展名 / 大小 / 空文件 / 文件签名 / 文件名"]
  URL --> UGUARD["地址 / 重定向 / DNS / 类型 / 大小 / 超时"]
  FGUARD --> JOB["SQLite 任务 / 幂等"]
  JOB --> PARSE["文本/DOCX 解析 / 可选 OCR"]
  UGUARD --> PARSE
  PARSE --> HASH["SHA-256 去重"]
  HASH --> CHUNK["分块 + 重叠 + 元数据"]
  CHUNK --> QUALITY["质量评分 / 索引状态"]
  CHUNK --> BM25["BM25"]
  CHUNK --> EMBED["嵌入模型提供方"]
  EMBED --> VECTOR["向量库"]
  QUALITY --> REGISTRY["SQLite 注册表"]
  PARSE -. "失败时清理临时文件" .-> CLEANUP["清理"]
```

URL 导入默认拒绝回环、内网、链路本地和特殊地址。校验不只发生在初始 URL，还覆盖重定向与最终响应，避免通过跳转绕过 SSRF 防线。

![不可信文件、URL、外部模型提供方和本地存储之间的信任边界](assets/security-boundaries.svg)

## 3. 问答检索时序

![十阶段多模态与图谱检索管线](assets/retrieval-pipeline.svg)

```mermaid
sequenceDiagram
  participant U as 用户
  participant W as Vue 工作台
  participant C as 会话 API
  participant E as RAG 引擎
  participant R as 混合检索器
  participant GR as 轻量图谱
  participant G as 回答生成器
  participant A as 引用审计

  U->>W: 提交问题、文档范围与检索参数
  W->>C: POST messages:stream
  C->>C: 保存用户/流式消息 + 最近六轮
  C->>E: 问题 + 知识库范围
  E->>E: 规范化 / 意图判断 / 查询改写
  E->>R: BM25 与向量并行召回
  opt strategy=hybrid_graph 或 auto 门控成立
    R->>GR: 实体种子 + 知识库范围 + 最大跳数
    GR-->>R: 有来源依据的路径 + 元素 ID
    R->>R: 加权 RRF
  end
  R->>R: 去重 / 父级上下文 / MMR / 重排
  R-->>E: 证据 + 检索追踪
  alt 证据不足
    E-->>C: refusal
    C-->>W: refusal → done
  else 证据满足门槛
    E->>G: 问题 + 受约束证据
    G-->>E: 带引用回答
    E->>A: 回答与实际引用片段
    A-->>E: 覆盖率、依据度与无支撑主张
    E-->>C: answer.delta* → answer.completed
    C-->>W: 最终引用、检索追踪与可信度审计 → done
  end
```

## 4. 元素、增强与图谱证据流

```mermaid
flowchart LR
  SOURCE["受控原件 / URL 正文"] --> PARSER["内置或隔离解析器"]
  PARSER --> IR["文档元素中间表示"]
  IR --> CONTEXT["有界上下文窗口"]
  CONTEXT --> ENRICH["模板 / 视觉增强"]
  ENRICH --> CACHE["版本化增强缓存"]
  ENRICH --> CHUNK["从元素派生的分块"]
  IR --> PROVENANCE["证据元素 + 文本范围"]
  PROVENANCE --> GRAPH["原生轻量图谱"]
  GRAPH --> PATH["种子 / 路径 / 证据 ID"]
  CHUNK --> HYBRID["BM25 + 向量"]
  PATH --> RRF["加权 RRF k=60"]
  HYBRID --> RRF
  RRF --> MMR["父级上下文 → MMR → 重排"]
  MMR --> GATE["拒答 + 引用门"]
```

这条链有两个硬边界：模型提供方提取的关系必须在原元素中找到 `evidence_span`；图谱输出必须先映射回本地分块才能进入排序。图边本身不能满足回答门槛。

## 5. 反馈与评测闭环

![反馈到 CI 门禁](assets/evaluation-loop.svg)

```mermaid
flowchart LR
  A["用户提问"] --> B["检索与回答"]
  B --> C["引用审计"]
  C --> D["用户反馈"]
  D --> E["评测草稿"]
  E --> F["运行评测"]
  F --> G["调整检索策略"]
  G --> B
```

## 6. 模型提供方与降级策略

```mermaid
flowchart LR
  CFG["环境变量配置"] --> EMB["嵌入适配器"]
  CFG --> VS["向量库适配器"]
  CFG --> RW["查询改写适配器"]
  CFG --> AG["回答适配器"]
  CFG --> ME["多模态增强适配器"]

  EMB -->|"默认离线"| MOCK["哈希 / 模拟"]
  EMB -->|"可选"| REAL_EMB["句向量模型 / OpenAI / Ollama"]
  VS --> MEMORY["内存"]
  VS --> CHROMA["Chroma"]
  VS --> PG["pgvector"]
  RW -->|"未配置或失败"| NOOP["不改写"]
  AG -->|"本地/测试显式允许"| TEMPLATE["模板回退"]
  AG -->|"可选"| RESPONSES["Responses / 聊天 / Ollama"]
  ME -->|"默认离线"| TEMPLATE_ENRICH["模板 + OCR/表格/公式"]
  ME -->|"可选"| VISION["Responses / 兼容视觉接口 / Ollama 视觉"]
```

默认演示链路完全离线，目的是让代码审查和面试演示可复现；真实模型、持久向量库和交叉编码器属于可替换增强项，不能把默认哈希嵌入的效果描述成生产检索质量。

## 7. 启动恢复与容器边界

![部署演进模式](assets/deployment-modes.svg)

SQLite 保存文档、知识库、会话、消息与任务。启动时恢复过期租约，再加载注册表并验证嵌入维度/模型/索引版本；只为兼容且缺失的文档重建索引。不兼容记录进入 `needs_rebuild`，不会混入当前检索。

![当前 SQLite 表、向量分块和生产工作区迁移边界](assets/data-model.svg)

字段、删除语义和迁移顺序见[SQLite 数据模型](data-model.md)。

Compose 的 Nginx 只暴露静态前端与 `/api` 代理，FastAPI `/ready` 返回当前模型提供方状态。前后端健康检查与 `depends_on: condition=service_healthy` 防止前端在后端未就绪时被标记为整体可用。

## 设计取舍

- 没有直接依赖 LangChain，是为了展示 RAG 核心链路和工程拆分能力。
- 默认模拟嵌入可离线运行，真实演示可切换本地/OpenAI 兼容嵌入。
- 普通模式隐藏复杂参数，专家模式展示检索追踪和调参入口。
- 引用审计先采用规则可解释实现，后续可升级为 NLI/LLM 判断器。

## 延伸阅读

- [产品巡游](product-tour.md)：从用户动作理解信息架构与状态。
- [检索与可信回答](retrieval-explained.md)：阶段、分数、拒答和诊断。
- [API 使用指南](api-reference.md)：端点、请求负载与错误语义。
- [配置指南](configuration.md)：模型提供方、存储、门槛与安全配置。
- [生产适配方案](production-adapters.md)：工作区、任务、pgvector 与对象存储。
- [安全威胁模型](security-model.md)：信任边界、已实现控制与剩余风险。
