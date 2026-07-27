# 生产现场验收手册

本文说明如何把 `0.4.0-rc.1` 的实现契约转成可审计的真实运行证据。所有证据写入被 Git 忽略的 `data/validation/`；仓库只提交采集器、校验规则和脱敏汇总格式，不提交密码、问题正文、私有 URL 或第三方原文。

> 这些命令不会把等待时间、机器生成候选或自动化请求伪装成人工/真实使用。14 天从第一个健康样本开始计算；人工标注必须逐条确认；真实问题必须由已登录用户主动勾选来源声明。

## 证据清单

| 文件 | 产生方式 | 1.0 用途 |
| --- | --- | --- |
| `indexing-summary.json` | `npm run corpus:validate-production` | 200 份非 fixture 文档及 SHA-256 对账 |
| `annotation-summary.json` | 质量面板人工审核 | 200 条人工标注 |
| `usage-summary.json` | `npm run usage:snapshot` | 100 次明确声明为本人提出的真实问题 |
| `external-providers.json` | `npm run providers:validate` | Ollama 原生与 OpenAI-compatible HTTP 契约 |
| `advanced-parser.json` | 高级 parser capability 与真实任务 | 高级解析器版本、能力和任务结果 |
| `restore-summary.json` | `npm run restore:drill-production` | PostgreSQL、pgvector、MinIO 破坏性恢复 |
| `chaos-summary.json` | `npm run chaos:compose -- --execute` | API、worker、Redis、PostgreSQL、MinIO 故障恢复 |
| `soak-events.jsonl` | `soak-monitor` | 追加式、SHA-256 串联的健康样本 |
| `soak-state.json` | `soak-monitor` | 连续运行时间与失败计数 |
| `real-benchmark.json` | 人工标注集评测 | 六项 1.0 质量阈值 |
| `release-evidence.json` | `npm run evidence:build` | `/api/system/readiness-report` 的发布门输入 |

## 1. 初始化真实生产 Compose

生成本机 secret files；命令默认拒绝覆盖已有文件：

```bash
python scripts/init_production_secrets.py
docker compose -f compose.production.yml config --quiet
docker compose -f compose.production.yml up --build --wait -d
```

生产模式要求真实嵌入/回答模型提供方，且 `PROVIDER_FALLBACK_ALLOWED=0`。模型提供方、元数据、pgvector、对象存储、队列、认证或隔离抓取工作进程不健康时 `/ready` 返回 503，不会静默切换到模板回答。

验证版覆盖配置将私有证据以只读方式提供给 API，并为稳定性监控器单独提供可写目录：

```bash
docker compose \
  -f compose.production.yml \
  -f compose.validation.yml \
  up --wait -d
```

## 2. 真实语料与人工标注

语料清单必须包含 200 个唯一 SHA-256、来源 URL 和许可证信息。下载后先做离线校验，再通过目录连接器进入与日常同步相同的任务、解析、嵌入、pgvector 和引用链路：

```bash
npm run corpus:real
npm run corpus:verify
npm run corpus:validate-production
```

`corpus:validate-production` 是增量且幂等的。短暂 502/503/504 会重试；终态失败会执行一次人工重试。最终必须同时满足 200 个成功任务、200 个活跃数据源条目、200 个文档以及完整哈希集合相等。

机器可预生成 200 条候选，但候选固定为 `draft`，不计入人工标注：

```bash
npm run annotations:prepare -- --seed
```

随后在“质量审计 → 人工评测队列”逐条补全预期答案/关键词、审核人 ID，并确认人工声明。系统只统计带审核人、审核时间和明确声明的记录；批量种子不会增加 `human_reviewed`。

## 3. 真实问题

生产问答区的“这是我本人此刻提出的真实问题”默认关闭。只有生产模式、已认证会话、用户主动勾选并发送的问题才记录匿名聚合证据；自动化端到端测试必须保持关闭。

```bash
npm run usage:snapshot
```

输出只包含计数、会话数和首末时间，不包含问题或答案正文。

## 4. 模型提供方与高级解析器

对本机 Ollama 同时执行原生 API 和 OpenAI-compatible API：

```bash
ollama pull qwen3:8b
ollama pull nomic-embed-text
npm run providers:validate
```

验收覆盖 `/api/version`、`/api/tags`、`/api/embed`、`/api/chat`、`/v1/models`、`/v1/embeddings`、`/v1/chat/completions` 和 `/v1/responses`。Responses 请求显式使用 `store:false`；报告不保存响应正文或凭据。远程 OpenAI-compatible 端点必须显式增加 `--allow-remote`，密钥仅从 `EXTERNAL_PROVIDER_API_KEY` 读取。

高级解析器是可选隔离配置，不进入默认镜像：

```bash
docker compose --profile advanced-parser build parser-worker
docker compose --profile advanced-parser up --wait -d parser-worker
npm run parser:validate-advanced
```

能力状态只能证明依赖可导入；验收还必须提交真实 PDF/DOCX/图片任务，等待终态并记录解析器版本、耗时、失败类型和是否发生回退。模型下载、系统库、架构或内存导致的失败必须保留为失败证据。

## 5. 破坏性恢复与混沌演练

只在 200 份语料全部索引、队列空闲且 `/ready` 为 200 后执行。恢复脚本会先创建带 SHA-256 manifest 的真实 PostgreSQL + MinIO 备份，再插入数据库哨兵、删除一个真实对象并执行覆盖恢复：

```bash
npm run restore:drill-production -- --confirm DESTROY_AND_RESTORE
```

通过条件包括：

- 数据库哨兵被恢复移除；
- 文档、资产、元素、任务、评测、消息、操作日志和向量计数完全一致；
- 所有向量维度为 768；
- 每个向量都能 join 到文档；
- 被删除对象恢复后大小与 SHA-256 完全一致。

随后依次 kill 并重建五个服务：

```bash
RAG_CHAOS_CONFIRM=I_UNDERSTAND \
  npm run chaos:compose -- --execute
```

每个场景前后对账文档 ID、任务幂等键和未发布 outbox；报告不能只保存 dry-run。

## 6. 14 天连续运行

恢复和混沌演练结束、全栈重新健康后再启动计时，避免把计划内破坏性操作计入连续运行：

```bash
npm run evidence:build
docker compose \
  -f compose.production.yml \
  -f compose.validation.yml \
  up -d --no-deps soak-monitor
```

每个事件包含前一事件 hash；任何编辑都会使验证失败。验证命令还会比较宿主机真实 UTC 与最后样本时间，并核对 state 的样本数、末尾 hash 和末次时间，避免“链本身正确但 monitor 已冻结”被误判为通过：

```bash
npm run soak:verify
npm run evidence:build
```

间隔超过配置上限、就绪状态非 200、模式不是 `production` 或任一必要组件不健康都会中断连续时间。脚本不会回填历史，也不会依据容器启动时间推断缺失样本。

## 7. Sentry

应用只在提供真实 `SENTRY_DSN` 时初始化 SDK，并在发送前移除 Authorization、Cookie、密钥、DSN、问题正文和私有 URL 参数。真实验收必须在目标 Sentry 项目中看到一条带发布版本/环境、无敏感正文的测试事件，并验证关闭 DSN 后应用仍正常启动。

```bash
npm run sentry:validate
```

自托管 Sentry 必须先满足其官方资源下限。资源不足不是“通过”；应记录主机/Docker 内存、所用配置、安装器输出和所需人工扩容步骤。

## 8. 发布判定

```bash
npm run evidence:build
curl --fail http://127.0.0.1:5173/api/system/readiness-report
```

只有 13 道发布门全部通过，且 14 天期间没有数据丢失级缺陷，才可以发布 `1.0.0`。`production_ready_claim` 在 RC 中固定为 `false`；缺少任何真实证据时项目仍应展示为 `0.4.0-rc.1 本地生产候选版`。

## 2026-07-23 实际执行快照

| 验收项 | 实际结果 |
| --- | --- |
| 真实语料 | 21 组许可证来源、200 文档、200 个活跃数据源条目、200 个成功任务 |
| 向量与对象 | 5,159 个 768 维 pgvector；200 个内容寻址 MinIO 原件；清单哈希全相等 |
| 破坏性恢复 | 通过；数据库哨兵移除，被删除对象按 SHA-256 恢复，恢复前后计数一致 |
| 混沌 | API、worker、Redis、PostgreSQL、MinIO 五类 kill/recreate 全通过，无重复文档/任务 |
| 高级解析器 | MinerU 3.4.4 + RAG-Anything 1.3.1 真实 PNG 任务通过，3 个元素；Docling/PaddleOCR 未安装 |
| 模型提供方 | Ollama 0.32.1 原生/兼容嵌入通过且为 768 维；三类 `qwen3:8b` 生成请求均 180 秒超时 |
| Sentry | 阻断：无 DSN，未发送真实事件；Docker 7.8 GiB，不满足 14 GiB 完整配置内存门 |
| 人工标注 / 真实问题 | 0/200、0/100；200 条机器候选只计 `draft` |
| 14 天观测 | 五次真实宿主机/运行时间隔均已入链并自然重置；截至 `2026-07-27T10:26:11Z` 共 943 个样本、23 个失败样本，最长连续 81,984 秒。链中保留 `2026-07-27T10:10:58Z` 的真实 `TimeoutError`，当前窗口从 `2026-07-27T10:16:11Z` 开始，尚未达标且不能回填 |

第四次恢复还复现了 Nginx 在后端容器重建后保留旧 Docker IP、导致前端 `/ready` 返回 502 的问题。前端现使用 Docker embedded DNS 按请求重新解析后端，CI 会强制替换后端后再次检查代理路径；稳定性校验器同时增加宿主机真实时间新鲜度与状态/链一致性门。修复没有删除卷、回填样本或抹去历史失败。

私有 JSON 证据和第三方原文受 `.gitignore` 保护；仓库只提交采集器、门槛和本脱敏摘要。
