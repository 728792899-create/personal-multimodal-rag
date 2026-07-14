# 已知边界

## Beta 范围内

- 默认 hash/mock embedding 是确定性离线替身，不代表真实语义向量质量；其拒答门会要求实质性词项证据。
- Template answer 主要用于可复现演示，不具备真实模型的综合表达能力。
- SQLite + 本地文件 + memory store 适合单实例、单用户/小团队 Beta，不适合水平扩展；知识库是数据范围，不是授权租户边界。
- 进程内限流在多副本之间不共享；生产应移到网关或 Redis。
- 本地索引 worker 有 SQLite 事实源、租约与三次尝试，但仍是单进程执行器；多实例、优先级、DLQ 和跨主机故障转移需要外部队列。
- URL 校验覆盖 DNS 解析、重定向与最终地址，但标准库连接没有做 IP pinning；高风险生产环境应使用隔离抓取服务防 DNS rebinding。
- DOCX 已保留标题、段落和表格文本；PDF/OCR 仍未实现通用表格结构、版面理解、图片语义 embedding、音频或视频内容分析。
- Citation audit 是透明的规则评估，不等同于人工事实核查或 NLI judge。

## 外部服务未完成项

- 没有在本次本地验收中连接真实 pgvector、S3-compatible object store、Redis、OIDC 或 Sentry 项目，因为没有提供外部服务和凭据。
- pgvector adapter 仍是单工作区表结构；多工作区前需要 schema/authorization 迁移。
- GitHub Actions 已在远端实际运行后端、前端/E2E、检索评测和 Docker Compose job；后续每次合并仍需以对应提交的检查结果为准。
- 没有生产容量/故障注入数据；上线前必须补文档数量、chunk 数、并发、OCR 和 provider 延迟压测。
- OpenAI、Ollama、pgvector 与 Sentry 只有 adapter/契约/配置边界；本轮没有凭据或外部服务，因此没有声称真实在线验收。

对应人工步骤与目标架构见 [production-adapters.md](production-adapters.md)。
