# 已知边界

## Beta 范围内

- 默认 hash/mock embedding 是确定性离线替身，不代表真实语义向量质量；其拒答门会要求实质性词项证据。
- Template answer 主要用于可复现演示，不具备真实模型的综合表达能力。
- SQLite + 本地文件 + memory store 适合单实例、单用户/小团队 Beta，不适合水平扩展。
- 进程内限流在多副本之间不共享；生产应移到网关或 Redis。
- 请求中同步解析/索引适合小文件；大文件与批量导入需要后台任务。
- URL 校验覆盖 DNS 解析、重定向与最终地址，但标准库连接没有做 IP pinning；高风险生产环境应使用隔离抓取服务防 DNS rebinding。
- OCR 只提取图片文本，尚未实现表格结构、版面理解、图片语义 embedding、音频或视频内容分析。
- Citation audit 是透明的规则评估，不等同于人工事实核查或 NLI judge。

## 外部服务未完成项

- 没有在本次本地验收中连接真实 pgvector、S3-compatible object store、Redis、OIDC 或 Sentry 项目，因为没有提供外部服务和凭据。
- pgvector adapter 仍是单工作区表结构；多工作区前需要 schema/authorization 迁移。
- GitHub Actions workflow 已本地等价验证，但远端运行状态要在推送后确认。
- 没有生产容量/故障注入数据；上线前必须补文档数量、chunk 数、并发、OCR 和 provider 延迟压测。

对应人工步骤与目标架构见 [production-adapters.md](production-adapters.md)。
