# RAG-Anything 对比审查：从解析框架到可审计证据工作台

## 审查范围

本轮以 HKUDS/RAG-Anything `1.3.1`、提交 [`a8c27f7`](https://github.com/HKUDS/RAG-Anything/commit/a8c27f7dbed6b5e8cab7924e9579ca60361106d7) 为固定基线，审查日期为 2026-07-15。上游代码采用 MIT License；本项目只通过可选依赖调用其公开接口并转换结果，没有复制上游实现。可选 worker 的依赖固定到完整 commit SHA，避免浮动分支在无审查的情况下改变解析行为。

审查覆盖 `raganything/parser.py`、`processor.py`、`modalprocessors.py`、`query.py`、`batch*.py`、`resilience.py`、配置、上下文感知说明、失败模式说明和测试目录。目标不是把本项目改写为 LightRAG 应用，而是找出哪些能力能补强现有“混合检索 + 引用审计 + 拒答 + 离线评测”主线。

## 上游值得学习的能力

### 统一解析输出和多解析器注册

RAG-Anything 把 MinerU、Docling、PaddleOCR 统一到 `content_list`，并提供 `register_parser`、`unregister_parser` 和能力枚举。这一层有效隔离了解析器差异，使 image、table、equation 等 modal processor 不必理解每个供应商的原始结构。

本项目吸收的是“parser-neutral IR”思想：`DocumentElement` 用 text、heading、image、table、equation、code 六种类型表达顺序、页码、bbox、标题路径、caption、footnote、表格矩阵、LaTeX、置信度和资源引用。RAG-Anything 的 `content_list` 只在 worker 边界出现，进入主应用前必须转换为本项目 IR；SQLite、引用和评测不会依赖上游内部对象。

### 上下文感知的多模态理解

上游会在分析图片、表格和公式时收集相邻页或相邻内容，支持窗口、token 上限、caption/header 开关和内容类型过滤。这比“把孤立图片直接交给 VLM”更符合真实文档语义，也是 0.3 `ContextWindowBuilder` 的直接设计依据。

本项目会进一步把上下文、provider、模型和 prompt version 纳入缓存键，并要求 enrichment 输出结构化 description、keywords、entities、relationships、confidence、warnings。任何关系必须保留 evidence element 和原文 span；生成描述可以帮助召回，但不能替代原始证据和引用门。

### 批处理、可插拔性和韧性

上游批处理支持递归目录、并发、进度、`dry-run` 与增量 manifest；resilience 模块提供同步/异步指数退避与 circuit breaker；callback manager 为阶段指标提供扩展点。这些设计比逐个文件手工上传更适合本地知识库建设。

本项目新增 `scripts/import_folder.py`，保留 recursive、dry-run、并发上限、知识库、解析 profile 和内容哈希 manifest，但仍通过公开 ingestion API 写入现有 SQLite job 状态机。worker/provider 的超时、重试、取消、熔断与脱敏指标会在后续堆叠 PR 继续落地。

### 图谱作为导航，而不是答案来源

RAG-Anything 借助 LightRAG 把多模态描述纳入实体和关系检索。它说明了图谱对多跳问题的价值，也提醒我们不能让另一个存储系统成为无法审计的第二事实来源。

本项目采用 native Graph-lite 默认实现：图节点、边和 mention 全部回指 document element；图谱只把检索导航到现有 evidence chunk，再通过加权 RRF 与 BM25/vector 结果融合。MMR、rerank、拒答和引用覆盖审计仍在图谱之后执行。LightRAG 只保留可选 adapter，不拥有文档、向量或引用事实。

## 不直接照搬的部分

| 上游做法/边界 | 本项目决定 | 原因 |
| --- | --- | --- |
| 主进程直接依赖 LightRAG 和重型解析运行时 | 默认镜像只含轻量内置解析；高级解析放入 `advanced-parser` profile | 保住全新克隆零 Key、零模型下载和小镜像路径 |
| parser 可接收 URL 并自行下载 | worker 只接收后端已校验的本地文件 | URL 获取继续由 SSRF 防护、大小/类型/重定向限制统一控制 |
| 解析结果可能包含本地资源路径或 public media URL | 所有原件和派生媒体进入内容寻址对象存储，只经受控 asset API 返回 | 避免本地路径泄露、静态目录越权和资源生命周期失控 |
| LightRAG storage 负责实体/关系与查询 | SQLite native graph 是 provenance 事实源，LightRAG 仅 adapter | 删除、知识库隔离、迁移、引用和离线评测需要一致边界 |
| LLM/VLM 生成的描述和关系直接增强知识图 | 关系必须有 evidence element、span、confidence、extractor version | 降低幻觉边进入检索并绕过拒答门的风险 |
| 通用框架面向多种集成，产品层状态不是主目标 | 保留持久会话、索引任务、引用审计、Trace、质量工作台和错误恢复 | 本项目目标是可稳定部署和可量化验收的产品 Beta |

## 已落地的 0.3 第一阶段

- SQLite schema v4 增加 `assets`、`document_elements`、`parser_runs`、`enrichment_cache`；迁移幂等且升级前备份。
- 原件写入 `sha256` 内容寻址对象存储，资源 API 不暴露 object key 或本地路径；引用归零后删除。
- PDF 保留文本 block/bbox/页内顺序和内嵌图片；DOCX 按 XML 原序保留标题、段落、表格、图片关系和 OMML 公式；图片保留 OCR/尺寸/格式元数据。
- chunk 从元素派生，保存 `element_ids`、`modality` 与 parent element，为精确引用和 parent-child retrieval 建立稳定接口。
- 可选 parser worker 以独立进程运行 RAG-Anything，提供 capability/job/status/cancel API，并把 `content_list` 转换为原生 IR。
- Compose worker 以非 root、只读根文件系统、`cap_drop: ALL`、独立 tmpfs、PID/内存上限运行；默认 Compose 不启动它。
- 批量目录 CLI 通过现有 ingestion API 入队，支持增量、并发上限和 `dry-run`。

## 尚未声称完成的外部验收

普通 CI 不下载 MinerU/Docling/PaddleOCR 模型，也不调用 OpenAI、Ollama、LightRAG 外部存储或付费 API。当前自动化验证的是：IR、对象生命周期、内置 PDF/DOCX、恶意 Office 防护、worker HTTP 契约、`content_list` adapter、受控资源 API 和默认离线路径。

部署者启用高级 profile 时仍需人工记录：镜像构建时间/大小、模型许可证、CPU/GPU 与内存峰值、真实扫描 PDF 的 OCR 质量、取消后子进程回收、超时/熔断、磁盘清理和固定多模态评测结果。没有这些证据前，README 不宣称高级解析器“生产验证通过”。

## 后续实现顺序

1. schema v5、上下文窗口、离线/视觉 enrichment 和 provenance-backed native graph。
2. `hybrid_graph/auto`、graph RRF、parent expansion 和完整 Trace。
3. 临时 query asset、图片提问、元素查看器、精确引用跳转和图谱可访问视图。
4. 100 条确定性多模态黄金集、parser/asset/graph CI、Docker 故障注入与 Browser 验收。

这一顺序让每层都能单独回滚：高级解析不可用时仍可内置解析；enrichment 不可用时仍可原始元素检索；图谱为空时仍执行原 hybrid；视觉 provider 不可用时仍能用 OCR/metadata 扩展查询；任何辅助能力都不能关闭拒答或引用审计。
