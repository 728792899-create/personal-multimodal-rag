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

- 本机 Ollama 的 embedding 原生/兼容接口已真实通过，但 `qwen3:8b` 的原生 chat、OpenAI-compatible chat-completions 与 Responses 均在 180 秒超时；生产默认模型仍需按目标硬件重新选型。没有 OpenAI 云端凭据，也没有连接托管 OIDC 或 Sentry 项目。
- 当前是服务端解析的单 workspace/单管理员边界；多 workspace、OIDC/RBAC 与数据库 RLS 顺延到 1.1。
- GitHub Actions 已在远端实际运行后端、前端/E2E、检索评测和 Docker Compose job；后续每次合并仍需以对应提交的检查结果为准。
- 已在本机隔离生产栈执行一次破坏性恢复和五类故障注入；这不替代目标容量环境复演。14 天链刚开始，人工标注、真实问题和真实语料质量基准仍未达标。
- Sentry SDK 与脱敏器已接入，但无 DSN，未验证真实事件；Docker 7.8 GiB 也不满足 full self-hosted profile 的资源门。
- MinerU 高级解析真实 PNG 已通过；Docling/PaddleOCR 未安装，复杂 PDF/DOCX、GPU/内存峰值和质量仍需目标 runner 验收。

对应人工步骤与目标架构见 [production-adapters.md](production-adapters.md)。
