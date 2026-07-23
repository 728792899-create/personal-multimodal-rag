# 1.0 发布证据与阻断项

`0.4.0-rc.1` 已提供 Production Local 的代码与运维契约，但仓库**没有宣称 production-ready，也没有发布 1.0.0**。`GET /api/system/readiness-report` 会读取部署方私有的 `RELEASE_EVIDENCE_PATH`，逐项返回机器可读 gate；缺少证据时状态固定为 `blocked`。

## 已完成的仓库内证据

- Demo、Local Production、Production 三种 profile 明确分层，production 禁止 template fallback。
- PostgreSQL/pgvector、S3/MinIO/ClamAV、Redis Streams/outbox/DLQ 和 session 认证适配。
- URL 抓取进入无凭据、无数据卷的隔离 worker；每次跳转重新解析并用已验证 IP 建立 socket。
- `/metrics` 输出低基数 Prometheus 指标；可选 OTLP/HTTP、Sentry scrubber 和 Grafana dashboard。
- 写入服务静默后的 PostgreSQL + S3/MinIO 一键备份、manifest SHA-256 验证、显式确认恢复与 Compose 故障注入入口。
- CodeQL、依赖审计、Trivy、SPDX SBOM、GitHub provenance 与 keyless Cosign 签名工作流。
- 离线固定 fixture 回归、前后端测试、Browser E2E 和默认 Compose 健康检查。

这些证据证明实现契约和离线回归，不等价于目标环境的持续运行结果。

## 1.0 必须同时满足

| Gate | 最低要求 | 当前公开仓库状态 |
| --- | ---: | --- |
| 有明确许可证的真实资料 | 20 份 | blocked：不提交第三方或私有语料 |
| 非 fixture 索引文档 | 200 份 | blocked：依赖真实部署 |
| 人工标注问题 | 200 条 | blocked：仓库固定集不能替代 |
| 真实使用问题 | 100 次 | blocked：不伪造流量 |
| 连续运行 | 14 天 | blocked：尚无公开 soak 证据 |
| 完整生产恢复 | 1 次且无数据丢失 | blocked：需要目标基础设施 |
| 数据丢失级缺陷 | 0 个未关闭 | blocked：需 soak 期确认 |
| Recall@5 / MRR | ≥ 0.85 / ≥ 0.75 | blocked：需真实语料报告 |
| 引用准确率 / 覆盖率 | ≥ 0.85 / ≥ 0.90 | blocked：需人工标注 |
| 拒答 / 可回答接受率 | ≥ 0.90 / ≥ 0.85 | blocked：需人工标注 |

复制 `eval/real/manifest.example.json` 到仓库外，填入可审计证据并设置：

```bash
export RAG_REAL_BENCHMARK_MANIFEST=/secure/evidence/release-evidence.json
export RELEASE_EVIDENCE_PATH="$RAG_REAL_BENCHMARK_MANIFEST"
npm run benchmark:real
curl --fail http://127.0.0.1:5173/api/system/readiness-report
```

命令只验证部署方证据，不会把仓库 fixture 计入真实门槛。CI 运行 `--contract-only`，确认空白样例保持 blocked；它不会伪造绿色的真实基准。

## 人工发布步骤

1. 在参考环境（8 vCPU、16 GB RAM、50,000 chunks）记录元数据 API、五并发检索和入队 p95。
2. 执行 `npm run backup:production`，在隔离环境运行 `npm run restore:production -- --confirm RESTORE`，核对对象 hash、行数、向量维度、索引版本和随机引用。
3. 分别注入 API、worker、Redis、PostgreSQL 与 MinIO 故障；确认任务恢复后无丢失、无重复文档。
4. 运行 14 天 soak，记录真实问题、Provider 错误、DLQ、拒答与引用指标。
5. 关闭所有数据丢失级缺陷后重新生成 readiness report；只有所有 gate 通过才创建 `v1.0.0` tag。
