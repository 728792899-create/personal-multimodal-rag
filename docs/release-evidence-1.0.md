# 1.0 发布证据与阻断项

`0.4.0-rc.1` 已提供本地生产候选版的代码与运维契约，但仓库**没有宣称生产就绪，也没有发布 1.0.0**。`GET /api/system/readiness-report` 会读取部署方私有的 `RELEASE_EVIDENCE_PATH`，逐项返回机器可读发布门；缺少证据时状态固定为 `blocked`。

## 已完成的仓库内证据

- 演示、本地生产、生产三种配置明确分层，生产模式禁止模板回答回退。
- PostgreSQL/pgvector、S3/MinIO/ClamAV、Redis Streams/发件箱/死信队列和会话认证适配。
- URL 抓取进入无凭据、无数据卷的隔离工作进程；每次跳转重新解析并用已验证 IP 建立套接字。
- `/metrics` 输出低基数 Prometheus 指标；可选 OTLP/HTTP、Sentry 脱敏器和 Grafana 仪表盘。
- 写入服务静默后的 PostgreSQL + S3/MinIO 一键备份、清单 SHA-256 验证、显式确认恢复与 Compose 故障注入入口。
- CodeQL、依赖审计、Trivy、SPDX SBOM、GitHub 来源证明与无密钥 Cosign 签名工作流。
- 离线固定测试集回归、前后端测试、浏览器端到端测试和默认 Compose 健康检查。

这些证据证明实现契约和离线回归，不等价于目标环境的持续运行结果。

## 1.0 必须同时满足

| 发布门 | 最低要求 | 当前公开仓库状态 |
| --- | ---: | --- |
| 有明确许可证的真实资料 | 20 份 | 通过：21 组私有清单，许可证与哈希已校验 |
| 非固定测试集索引文档 | 200 份 | 通过：200 文档 / 200 任务 / 5,159 向量 |
| 人工标注问题 | 200 条 | 阻断：200 条草稿，人工确认 0 |
| 真实使用问题 | 100 次 | 阻断：明确来源声明计数 0 |
| 连续运行 | 14 天 | 进行中：历史间隔均保留；最长连续 81,984 秒。`2026-07-27T10:10:58Z` 的真实 `TimeoutError` 后，当前窗口于 `2026-07-27T10:16:11Z` 自然重置，不能回填 |
| 完整生产恢复 | 1 次且无数据丢失 | 通过：PostgreSQL/pgvector/MinIO 破坏性恢复对账通过 |
| 数据丢失级缺陷 | 0 个未关闭 | 阻断：需稳定性运行期确认 |
| Recall@5 / MRR | ≥ 0.85 / ≥ 0.75 | 阻断：需真实语料报告 |
| 引用准确率 / 覆盖率 | ≥ 0.85 / ≥ 0.90 | 阻断：需人工标注 |
| 拒答 / 可回答接受率 | ≥ 0.90 / ≥ 0.85 | 阻断：需人工标注 |

复制 `eval/real/manifest.example.json` 到仓库外，填入可审计证据并设置：

```bash
export RAG_REAL_BENCHMARK_MANIFEST=/secure/evidence/release-evidence.json
export RELEASE_EVIDENCE_PATH="$RAG_REAL_BENCHMARK_MANIFEST"
npm run benchmark:real
curl --fail http://127.0.0.1:5173/api/system/readiness-report
```

命令只验证部署方证据，不会把仓库固定测试集计入真实门槛。CI 运行 `--contract-only`，确认空白样例保持 `blocked`；它不会伪造绿色的真实基准。

## 人工发布步骤

1. 在参考环境（8 vCPU、16 GB RAM、50,000 分块）记录元数据 API、五并发检索和入队 p95。
2. 执行 `npm run backup:production`，在隔离环境运行 `npm run restore:production -- --confirm RESTORE`，核对对象哈希、行数、向量维度、索引版本和随机引用。
3. 分别注入 API、工作进程、Redis、PostgreSQL 与 MinIO 故障；确认任务恢复后无丢失、无重复文档。
4. 运行 14 天稳定性运行，记录真实问题、模型提供方错误、死信队列、拒答与引用指标。
5. 关闭所有数据丢失级缺陷后重新生成就绪报告；只有所有发布门通过才创建 `v1.0.0` 标签。

本机还真实通过五类 Compose 故障注入与 MinerU PNG 解析。Ollama 嵌入契约通过，`qwen3:8b` 生成接口超时；Sentry 无 DSN，未发送事件。这些失败/阻断项不会被固定测试集或能力探针替代。
