# RAG-Anything 对比审查：从解析框架到可审计证据工作台

## 审查范围

本轮以 HKUDS/RAG-Anything `1.3.1`、提交 [`a8c27f7`](https://github.com/HKUDS/RAG-Anything/commit/a8c27f7dbed6b5e8cab7924e9579ca60361106d7) 为固定基线，审查日期为 2026-07-15。上游代码采用 MIT 许可证；本项目只通过可选依赖调用其公开接口并转换结果，没有复制上游实现。可选工作进程的依赖固定到完整提交 SHA，避免浮动分支在无审查的情况下改变解析行为。

审查覆盖 `raganything/parser.py`、`processor.py`、`modalprocessors.py`、`query.py`、`batch*.py`、`resilience.py`、配置、上下文感知说明、失败模式说明和测试目录。目标不是把本项目改写为 LightRAG 应用，而是找出哪些能力能补强现有“混合检索 + 引用审计 + 拒答 + 离线评测”主线。

## 上游值得学习的能力

### 统一解析输出和多解析器注册

RAG-Anything 把 MinerU、Docling、PaddleOCR 统一到 `content_list`，并提供 `register_parser`、`unregister_parser` 和能力枚举。这一层有效隔离了解析器差异，使图片、表格、公式等模态处理器不必理解每个供应商的原始结构。

本项目吸收的是“解析器中立的中间表示”思想：`DocumentElement` 用 text、heading、image、table、equation、code 六种类型表达顺序、页码、边界框、标题路径、图注、脚注、表格矩阵、LaTeX、置信度和资源引用。RAG-Anything 的 `content_list` 只在工作进程边界出现，进入主应用前必须转换为本项目中间表示；SQLite、引用和评测不会依赖上游内部对象。

### 上下文感知的多模态理解

上游会在分析图片、表格和公式时收集相邻页或相邻内容，支持窗口、token 上限、caption/header 开关和内容类型过滤。这比“把孤立图片直接交给 VLM”更符合真实文档语义，也是 0.3 `ContextWindowBuilder` 的直接设计依据。

本项目把上下文、模型提供方、模型和提示版本纳入缓存键，并要求内容增强输出结构化描述、关键词、实体、关系、置信度、警告。任何关系必须保留证据元素和原文跨度；生成描述可以帮助召回，但不能替代原始证据和引用门。

### 批处理、可插拔性和韧性

上游批处理支持递归目录、并发、进度、`dry-run` 与增量 manifest；resilience 模块提供同步/异步指数退避与 circuit breaker；callback manager 为阶段指标提供扩展点。这些设计比逐个文件手工上传更适合本地知识库建设。

本项目新增 `scripts/import_folder.py`，保留递归、试运行、并发上限、知识库、解析配置和内容哈希清单，但仍通过公开导入 API 写入现有 SQLite 任务状态机。高级解析与视觉内容增强共用指数退避、抖动和熔断器；任务取消、错误与指标仍只保存脱敏数据。

### 图谱作为导航，而不是答案来源

RAG-Anything 借助 LightRAG 把多模态描述纳入实体和关系检索。它说明了图谱对多跳问题的价值，也提醒我们不能让另一个存储系统成为无法审计的第二事实来源。

本项目采用原生轻量图谱默认实现：图节点、边和提及全部回指文档元素；图谱只把检索导航到现有证据分块，再通过加权 RRF 与 BM25/向量结果融合。MMR、重排、拒答和引用覆盖审计仍在图谱之后执行。LightRAG 只保留可选适配器，不拥有文档、向量或引用事实。

## 不直接照搬的部分

| 上游做法/边界 | 本项目决定 | 原因 |
| --- | --- | --- |
| 主进程直接依赖 LightRAG 和重型解析运行时 | 默认镜像只含轻量内置解析；高级解析放入 `advanced-parser` 配置 | 保住全新克隆零密钥、零模型下载和小镜像路径 |
| 解析器可接收 URL 并自行下载 | 工作进程只接收后端已校验的本地文件 | URL 获取继续由 SSRF 防护、大小/类型/重定向限制统一控制 |
| 解析结果可能包含本地资源路径或公开媒体 URL | 所有原件和派生媒体进入内容寻址对象存储，只经受控资源 API 返回 | 避免本地路径泄露、静态目录越权和资源生命周期失控 |
| LightRAG 存储负责实体/关系与查询 | SQLite 原生图谱是来源证明事实源，LightRAG 仅适配器 | 删除、知识库隔离、迁移、引用和离线评测需要一致边界 |
| LLM/VLM 生成的描述和关系直接增强知识图 | 关系必须有证据元素、跨度、置信度、提取器版本 | 降低幻觉边进入检索并绕过拒答门的风险 |
| 通用框架面向多种集成，产品层状态不是主目标 | 保留持久会话、索引任务、引用审计、检索追踪、质量工作台和错误恢复 | 本项目目标是可稳定部署和可量化验收的产品候选版 |

## 已落地的 0.3 第一阶段

- SQLite schema v4 增加 `assets`、`document_elements`、`parser_runs`、`enrichment_cache`；迁移幂等且升级前备份。
- 原件写入 `sha256` 内容寻址对象存储，资源 API 不暴露 object key 或本地路径；引用归零后删除。
- PDF 保留文本块/边界框/页内顺序和内嵌图片；DOCX 按 XML 原序保留标题、段落、表格、图片关系和 OMML 公式；图片保留 OCR/尺寸/格式元数据。
- 分块从元素派生，保存 `element_ids`、`modality` 与父元素，为精确引用和父子检索建立稳定接口。
- 可选解析工作进程以独立进程运行 RAG-Anything，提供能力/任务/状态/取消 API，并把 `content_list` 转换为原生中间表示。
- Compose worker 以非 root、只读根文件系统、`cap_drop: ALL`、独立 tmpfs、PID/内存上限运行；默认 Compose 不启动它。
- 批量目录 CLI 通过现有 ingestion API 入队，支持增量、并发上限和 `dry-run`。

## 已落地的 0.3 第二阶段

- SQLite 架构 v5 增加 `graph_nodes`、`graph_edges` 和 `entity_mentions`；每条可检索边都要求证据元素、原文跨度、置信度和提取版本。
- `ContextWindowBuilder` 在固定字符预算内收集相邻页/元素，模板回答、OpenAI Responses、OpenAI-compatible 视觉接口和 Ollama 视觉接口共用严格内容增强架构与版本化缓存。
- OpenAI Responses 视觉请求使用 `input_image`、可配置 detail、`text.format` JSON Schema 和 `store:false`；自动化只使用 mock transport。
- 原生轻量图谱提取显式英文/中文关系与表格三元组，拒绝没有原文跨度的模型提供方关系，并按知识库隔离节点、边与提及。
- `hybrid_graph` 通过 `k=60`、默认图谱权重 `0.25` 的加权 RRF 融合证据分块；`auto` 只有在多实体、带来源证明的路径成立时启用，之后仍执行 MMR、重排、拒答与引用审计。
- 可选 `LightRAGNavigationAdapter` 只接受能解析到当前本地知识库元素的证据 ID；外部图不会写入 SQLite，也不能绕过引用门。
- 文档质量与系统指标新增边界框、OCR、图注、表格、公式、孤立资源、图谱覆盖、模态数量、回退与图谱命中。

## 尚未声称完成的外部验收

普通 CI 不下载 MinerU/Docling/PaddleOCR 模型，也不调用 OpenAI、Ollama、LightRAG 外部存储或付费 API。当前自动化验证的是：中间表示、对象生命周期、内置 PDF/DOCX、恶意 Office 防护、工作进程 HTTP 契约、`content_list` 适配器、受控资源 API 和默认离线路径。

部署者启用高级配置时仍需人工记录：镜像构建时间/大小、模型许可证、CPU/GPU 与内存峰值、真实扫描 PDF 的 OCR 质量、取消后子进程回收、超时/熔断、磁盘清理和固定多模态评测结果。没有这些证据前，README 不宣称高级解析器“生产验证通过”。

## 后续实现顺序

1. ~~schema v5、上下文窗口、离线/视觉 enrichment 和 provenance-backed native graph。~~
2. ~~`hybrid_graph/auto`、graph RRF、可配置 parent context 和后端 Trace。~~
3. 临时查询附件、图片提问、元素查看器、精确引用跳转和图谱可访问视图。
4. 100 条确定性多模态黄金集、解析器/资源/图谱 CI、Docker 故障注入与浏览器验收。

这一顺序让每层都能单独回滚：高级解析不可用时仍可内置解析；内容增强不可用时仍可原始元素检索；图谱为空时仍执行原混合检索；视觉模型提供方不可用时仍能用 OCR/元数据扩展查询；任何辅助能力都不能关闭拒答或引用审计。
