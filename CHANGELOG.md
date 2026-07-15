# Changelog

本项目遵循面向 Beta 的语义化版本记录。当前尚未发布正式稳定 API。

## Unreleased

### Added

- 0.3 多模态统一 IR：text、heading、image、table、equation、code 元素，保留页码、顺序、bbox、标题路径、结构化表格和精确引用 ID。
- 内容寻址本地对象存储、原件受控下载、PDF/DOCX 内嵌图片物化、引用计数与删除/失败回滚。
- SQLite schema v4：`assets`、`document_elements`、`parser_runs`、`enrichment_cache`，旧文档明确标记原件可用性。
- 可选隔离 parser worker，固定 RAG-Anything `1.3.1`/`a8c27f7`，支持 MinerU、Docling、PaddleOCR profile 与 `content_list` 转换。
- 递归/增量/并发上限/`dry-run` 批量目录导入 CLI，以及解析器能力与元素/资源 API。
- [RAG-Anything 固定提交对比审查](docs/comparative-review-rag-anything.md)。
- SQLite schema v5 provenance-backed Graph-lite、中文/英文显式关系、表格三元组、知识库隔离与受控 LightRAG 导航 adapter。
- 上下文感知 template/OpenAI Responses/OpenAI-compatible/Ollama vision enrichment、版本化缓存、结构化输出与 `store:false` Responses 契约。
- `hybrid_graph`/`auto`、加权 RRF、模态过滤、可配置 parent context，以及 graph seed/path/evidence Trace。
- Provider/parser 指数退避、抖动和熔断；版面、OCR、caption、表格、公式、孤立资源与图谱覆盖指标。
- 24 小时 Query Asset：最多 4 张 PNG/JPEG/WEBP/非动画 GIF，单张 10 MB，支持 OCR/视觉查询增强、过期清理与知识库隔离。
- 图片提问 SSE 事件、文档元素查看器、精确引用跳转、Graph SVG/键盘表格、十阶段 Trace 与多模态质量面板。
- 100 条固定黄金集与 12 项阈值；新增 multimodal-eval、graph-eval、parser-contract 和 asset-security CI。

### Fixed

- 协作取消现在由 Worker 明确提交 `cancelled` 终态并清除租约；重启时遇到过期的 `cancelling` 任务也会收敛为终态，不再形成无法领取的 `queued` 任务。
- 高级解析器的取消信号使用独立异常传播，不会被本地 parser fallback 捕获后额外执行内置解析；超时与取消都会尽力清理远端临时任务。

## 0.2.0-beta

### Added

- Durable Local 数据层：版本化 SQLite 迁移、默认知识库、持久会话与租约索引任务。
- 知识库 CRUD、隔离检索、异步文件/URL 入库、进度、取消、三次重试和进程恢复。
- DOCX 标题/段落/表格解析及 Office ZIP 结构、展开体积、条目和压缩比防护。
- OpenAI Responses、OpenAI-compatible Chat 与 Ollama 轻量 adapter；只读 Provider 状态。
- 稳定 SSE 会话协议、流式正文、断连取消、拒答与完成后引用审计。
- 知识库删除保护：活动任务阻止删除，强制删除清理终态任务并自动修复持久会话范围。
- 专家参数前置校验与可读 FastAPI 错误；独立新问题不再继承旧会话词项，通用词重叠不能绕过拒答门。
- 40 条黄金集及知识库隔离、多轮、DOCX 表格、索引版本回归；新增回答接受准确率门槛。
- [`rag-web-ui` 固定提交对比审查](docs/comparative-review-rag-web-ui.md)与[0.2 迁移/回滚指南](docs/durable-local-0.2.md)。

- 作品集级 README 主视觉、系统全景、七阶段检索、质量闭环与部署拓扑。
- 产品巡游、检索原理、API、配置、测试评测、运维、FAQ、路线图和文档中心。
- 贡献指南、视觉资产来源与 Browser 截图维护说明。
- 英文项目入口、端到端案例、代码导览、数据模型、安全威胁模型和固定集评测结果。
- 请求生命周期、SQLite 数据、安全边界、前端状态机与 40-case 成绩卡五张可审查 SVG。
- 上传/URL、引用上下文、质量审计、反馈 eval draft 和错误重试五张真实 Browser 截图。
- 1280×640 GitHub social preview，以及图片格式、尺寸、大小与清单完整性校验。

## 0.1.0-beta

### Added

- PDF、Markdown、文本、图片 OCR 与公开 URL 导入。
- BM25、向量检索、融合、MMR、rerank、无证据拒答和引用审计。
- 普通模式与专家模式、检索 Trace、知识卡片、反馈和 eval draft。
- 离线 mock/template/memory 模式与 Docker Compose 一键启动。
- pytest、Vitest、Playwright、固定黄金集、GitHub Actions 与健康检查。
- 上传/URL 安全边界、请求 ID、限流、脱敏日志和可选 Sentry。

### Known limitations

- 默认 hash embedding 和 template answer 只用于离线演示。
- 当前是单实例、单 workspace Beta；生产外部服务尚需部署方接入。
- 固定黄金集规模较小，不代表真实开放域质量。
