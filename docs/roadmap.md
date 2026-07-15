# 路线图

路线图按风险和验证价值排序，不按“功能数量”排序。默认离线 Demo 必须一直可运行，新基础设施通过 adapter 增强，而不是成为仓库启动的前置条件。

## 已交付：0.1 Beta 基线

- [x] 多格式上传、公开 URL 导入与可选 OCR。
- [x] BM25 + vector + fusion + MMR + rerank。
- [x] 无证据拒答、引用上下文与引用审计。
- [x] 普通/专家模式、响应式布局和错误恢复。
- [x] 反馈生成 eval draft。
- [x] 30 条固定黄金集和四项 CI 阈值（0.2 已扩展）。
- [x] pytest、Vitest、Playwright、Docker Compose 健康检查。
- [x] 上传/URL 安全、限流、脱敏日志与可选 Sentry。

## 已交付：0.2 Durable Local

目标：让单用户长期使用时的数据、索引和升级更可靠。

- [x] 本地 sentence-transformer embedding profile（可选依赖）。
- [x] Chroma collection 的维度、模型和 index version 检查。
- [x] chunker/embedding/index version 写入 metadata，不兼容文档隔离为 `needs_rebuild`。
- [x] SQLite 任务、本地 worker、租约恢复、幂等、取消与三次重试。
- [x] 多知识库、持久会话、稳定 SSE 与 Provider 状态。
- [x] DOCX 标题、段落、表格和 ZIP-bomb 防护。
- [x] 40 条固定黄金集、五项 CI 阈值及 KB/多轮/DOCX/版本 case。

退出条件：代码级重启恢复、迁移、维度门、失败重试和取消已有自动化证据；真实外部 Provider/存储和人工备份恢复仍需部署环境验证。

## 当前：0.3 Multimodal Intelligence

目标：把原件、版面元素、图片/表格/公式和图谱导航纳入可重建、可引用、可评测的同一证据模型，同时保持零 Key 默认路径。

- [x] schema v4 多模态元素、内容寻址对象存储、原件与派生资源生命周期。
- [x] PDF/DOCX 原始顺序、bbox/表格/图片与 element-driven chunk；内置解析器继续零下载。
- [x] 隔离 parser worker 契约与 RAG-Anything `content_list` adapter；高级镜像仅手动 profile。
- [x] 递归、增量、并发受控的批量目录导入 CLI。
- [x] schema v5 enrichment cache、provenance-backed Graph-lite 与 `hybrid_graph/auto`。
- [x] 上下文窗口、template/Responses/compatible/Ollama enrichment、重试与熔断。
- [x] 可配置 parent context、模态过滤、graph RRF 和后端 Trace 契约。
- [ ] 图片提问、元素查看器、graph Trace 与精确引用跳转。
- [ ] 扩展至 100 条多模态黄金集和 parser/asset/graph 专项 CI。
- [ ] 解析质量、OCR、caption、表格、公式和图谱覆盖 dashboard（后端指标已完成，UI 待交付）。

退出条件：对象/元素迁移与删除、解析 fallback/取消、图谱 provenance、图片提问、100 条固定集及 Browser 普通/专家/窄屏验收均有真实自动化或人工证据。

## 后续版本：0.4 Small-team Beta

目标：建立真正的身份、工作区和异步任务边界。

- [ ] OIDC/OAuth2 与可信 workspace claims。
- [ ] PostgreSQL + pgvector schema migration 与行级授权。
- [ ] S3-compatible 对象存储、签名上传和病毒扫描。
- [ ] Redis/队列 worker、幂等键、retry 与 DLQ。
- [ ] workspace 配额、审计事件和管理员恢复流程。
- [ ] OpenTelemetry traces、metrics backend 与 Sentry 告警。
- [ ] 多副本限流、并发和容量测试。

退出条件：跨 workspace 越权测试、备份恢复、删除、故障注入与回滚演练通过。

## 研究方向

- 多模态版面模型、表格结构恢复和图片语义 embedding；
- parent-child retrieval 与更细粒度 citation span；
- learned sparse retrieval 和可插拔 cross-encoder；
- NLI/LLM judge 与人工抽样结合的引用评估；
- query decomposition、多跳检索和冲突证据呈现；
- 真实用户反馈采样、漂移检测和在线 shadow evaluation。

研究功能必须先定义离线替代、失败模式、成本上限和可量化验收，再进入默认路径。

## 明确不做

- 在没有 workspace 授权前宣称多租户隔离；
- 把默认 hash embedding 指标描述成真实语义检索效果；
- 让在线 LLM judge 成为唯一质量门；
- 为了提高 Recall 关闭拒答或引用检查；
- 把 API Key、共享 token 或数据库凭据编译进前端；
- 以破坏离线一键启动为代价增加外部依赖。
