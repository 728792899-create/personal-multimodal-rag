# 已知边界

## Beta 范围内

- 默认 hash/mock embedding 是确定性离线替身，不代表真实语义向量质量；其拒答门会要求实质性词项证据。
- Template answer 主要用于可复现演示，不具备真实模型的综合表达能力。
- Demo 的 SQLite + 本地文件 + memory store 适合单实例，不适合水平扩展；Production profile 已提供 PostgreSQL/pgvector、S3/MinIO 和 Redis adapter，但尚未完成仓库外真实容量与 14 天运行门。
- 进程内限流在多副本之间不共享；生产应移到网关或 Redis。
- 本地索引 worker 有 SQLite 事实源、租约与三次尝试，但仍是单进程执行器；多实例、优先级、DLQ 和跨主机故障转移需要外部队列。
- Demo/Local 的标准库 URL 路径仍主要用于可复现开发；Production 强制使用无 secret、无数据卷的隔离 fetch worker，对每次重定向重新解析并把连接固定到已验证公网 IP。
- 内置 parser 已保留 PDF/DOCX 的有序元素、常见表格、公式、嵌入图片、bbox 与可选 OCR，但复杂跨页表格、手写内容和任意版面仍可能需要隔离的 MinerU/Docling/PaddleOCR profile；音频、视频与专用视觉 embedding 尚未实现。
- Citation audit 是透明的规则评估，不等同于人工事实核查或 NLI judge。

## 外部服务未完成项

- 没有在本次本地验收中连接仓库外真实 Ollama/OpenAI、托管 PostgreSQL/S3/Redis、OIDC 或 Sentry 项目，因为没有提供外部服务和凭据；Compose 内的 contract 不能替代真实长期运行。
- 当前是服务端解析的单 workspace/单管理员边界；多 workspace、OIDC/RBAC 与数据库 RLS 顺延到 1.1。
- GitHub Actions 已在远端实际运行后端、前端/E2E、检索评测和 Docker Compose job；后续每次合并仍需以对应提交的检查结果为准。
- 故障注入脚本默认只输出计划，备份/恢复默认只校验；尚无生产容量、真实破坏性演练和 14 天 soak 数据。执行前必须准备隔离环境和显式确认。
- OpenAI、Ollama、pgvector 与 Sentry 只有 adapter/契约/配置边界；本轮没有凭据或外部服务，因此没有声称真实在线验收。
- 高级 parser 镜像已有手动 workflow 和 mock contract，但真实模型、GPU/内存峰值及扫描件质量仍必须在带 `rag-parser` 标签的部署 runner 验收。

对应人工步骤与目标架构见 [production-adapters.md](production-adapters.md)。
