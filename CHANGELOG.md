# Changelog

本项目遵循面向 Beta 的语义化版本记录。当前尚未发布正式稳定 API。

## Unreleased

## 0.2.0-beta

### Added

- Durable Local 数据层：版本化 SQLite 迁移、默认知识库、持久会话与租约索引任务。
- 知识库 CRUD、隔离检索、异步文件/URL 入库、进度、取消、三次重试和进程恢复。
- DOCX 标题/段落/表格解析及 Office ZIP 结构、展开体积、条目和压缩比防护。
- OpenAI Responses、OpenAI-compatible Chat 与 Ollama 轻量 adapter；只读 Provider 状态。
- 稳定 SSE 会话协议、流式正文、断连取消、拒答与完成后引用审计。
- 知识库删除保护：活动任务阻止删除，强制删除清理终态任务并自动修复持久会话范围。
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
