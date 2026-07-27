# 验证基线与最终证据

执行日期：2026-07-14（Asia/Shanghai）。所有测试都清空 OpenAI/answer/rewrite Key，并使用 `mock + memory + template + no rewrite`。没有调用付费 API。

## 修改前真实基线

| 项目 | 结果 |
| --- | --- |
| 后端测试 | 35 passed，5 个 PyMuPDF/SWIG deprecation warning |
| 前端生产构建 | 通过；JS 113.29 kB（gzip 38.72），CSS 19.10 kB（gzip 4.38） |
| Demo smoke | 1 passed |
| 旧检索评测 | 30 条、单一 `rag-notes.md`；Recall@5 1.0000、MRR 0.8333、citation precision 1.0000 |
| 真实本地启动 | `/health` 正常；5 份样例完成索引；创建 4 条 eval draft |

旧评测只有一份来源文档，引用指标偏乐观；该结果仅作基线，不作为最终质量声明。

## 0.1 加固分支验收（历史）

`npm run verify`：

| 项目 | 结果 |
| --- | --- |
| 文档检查 | 30 个 Markdown、10 个 SVG、12 个 raster image 通过链接、alt、格式、清单与可访问性校验 |
| 后端 pytest | 54 passed |
| 前端 Vitest | 3 files / 8 tests passed |
| `npm run build` | 通过；JS 113.32 kB（gzip 40.42），CSS 23.27 kB（gzip 4.98） |
| Demo smoke | 1 passed |
| Playwright | 4 passed：桌面 + mobile Chromium |
| 黄金集 | 30 条（24 answerable / 6 refusal），全部阈值通过 |

黄金集实测：Recall@5 1.0000、MRR 1.0000、首条引用准确率 1.0000、拒答准确率 1.0000。阈值分别为 0.90 / 0.75 / 0.75 / 0.80。

## 0.2 Durable Local 当前验收

2026-07-14 在 `codex/rag-web-ui-durable-local` 执行全套验收。首次运行的 E2E locator 因任务卡和文档卡同名发生严格定位冲突，按可访问角色修正后 6/6 通过；首次打开真实旧 SQLite 又暴露迁移索引顺序错误，修复后加入 legacy schema 回归。系统 Chrome 终验进一步发现 FastAPI 校验数组显示为 `[object Object]`，以及无条件拼接会话历史会让跨主题问题绕过拒答门；两项均先复现、修复并加入回归。

| 项目 | 真实结果 |
| --- | --- |
| 文档/图片 | 32 Markdown、10 SVG、12 raster 全部通过；secret scan 通过 |
| 后端 pytest | 73 passed；含旧表迁移/备份、KB、任务、DOCX、Provider、SSE、多轮与跨主题拒答 |
| 前端 Vitest | 4 files / 13 tests passed |
| `npm run build` | 通过；JS 128.37 kB（gzip 45.00），CSS 25.66 kB（gzip 5.35） |
| Demo smoke | 1 passed |
| Playwright | 6 passed；desktop Chromium + 390px mobile Chromium |
| 黄金集 | 40（32 answerable / 8 refusal），五项阈值全部通过 |

黄金集实测：Recall@5 1.0000、MRR 0.9844、首条引用准确率 0.9688、拒答准确率 1.0000、回答接受准确率 1.0000。

## 0.3 Graph Retrieval 第二阶段验收

2026-07-15 在 `codex/graph-retrieval` 执行 `npm run verify`。所有 Provider 测试继续使用 template 或 `httpx.MockTransport`，Key 被显式清空，没有外部模型请求。

| 项目 | 真实结果 |
| --- | --- |
| 文档/图片 | 33 Markdown、10 SVG、12 raster 通过；secret scan 检查 210 个候选 |
| 后端 pytest | 98 passed；新增 v4→v5 迁移、Graph provenance/KB 隔离、视觉契约、重试/熔断、fallback 观测与 LightRAG 白名单 |
| 前端 Vitest | 4 files / 13 tests passed |
| `npm run build` | 通过；JS 128.65 kB（gzip 45.09），CSS 25.66 kB（gzip 5.35） |
| Demo smoke | 1 passed |
| Playwright | 6 passed；desktop Chromium + 390px mobile Chromium |
| 黄金集 | 40（32 answerable / 8 refusal），五项原有阈值全部通过 |

黄金集保持 Recall@5 1.0000、MRR 0.9844、首条引用准确率 0.9688、拒答准确率 1.0000、回答接受准确率 1.0000。Graph 专项当前由 13 个确定性后端契约覆盖；100 条多模态/graph 固定集和 Browser 图谱 UI 验收属于第三阶段，尚未提前声称完成。

## 0.3 Multimodal Query & Evaluation 第三阶段验收

2026-07-15 在 `codex/multimodal-query-ui-eval` 执行专项与全链路验证。测试配置继续强制 `mock + memory + template`，没有付费 API 请求。

| 项目 | 真实结果 |
| --- | --- |
| 文档/图片 | 33 Markdown、10 SVG、16 raster 通过；secret scan 检查 244 个候选 |
| 后端 pytest | 110 passed；Query Asset、附件 SSE、协作取消终态、Parser 取消/超时，以及 SQLite + 对象存储隔离恢复均有契约测试 |
| 前端 Vitest | 5 files / 15 tests passed；新增图片附件与 Graph SVG/等价表格 |
| `npm run build` | 通过；JS 145.54 kB（gzip 50.26），CSS 29.78 kB（gzip 5.99） |
| Playwright | 8 passed；desktop + 390px mobile，含图片提问、Graph 控件与键盘表格 |
| Query Asset fixture | 12 个真实 PNG，全部 640×360、非动画、小于 1 MB |
| 黄金集 | 100（89 answerable / 11 refusal），12 项阈值全部通过 |
| 多模态专项 | 44 cases；Modality Recall@5、表格单元、Caption、公式均为 1.0000 |
| Graph 专项 | 10 cases；path precision、evidence coverage、multi-hop Recall@5 均为 1.0000 |

全集实测：Recall@5 1.0000、MRR 0.9888、首条引用 0.9775、拒答 1.0000、可回答接受 1.0000。详细 case 行位于 `eval/reports/latest.md`；上述数据只是固定仓库 fixture 回归信号。

Docker 实栈重新构建后，`/ready` 返回 schema version 5 与 `mock / memory / template`。真实 API 创建临时知识库，异步导入 Graph fixture 到 `succeeded`，上传 640×360 PNG 后按序收到 `query.enrichment.started → query.enrichment.completed → retrieval.started → retrieval.completed → answer.delta → answer.completed → done`；`hybrid_graph` 返回 4 个 seed、3 条路径和 1 个 evidence element。

## Docker Compose

- `docker compose config --quiet` 通过。
- 前端、后端镜像从干净 build context 构建成功。
- `docker compose up --wait --wait-timeout 120 -d` 成功；两个服务均为 healthy。
- `GET :8010/ready` 返回 `mock / memory / template`。
- `GET :5173/healthz` 返回 `ok`。
- `GET :5173/api/documents` 通过 Nginx 代理访问后端。
- 真实停止/重启后端后，SQLite 中 5 份文档自动重建缺失 memory index，问答返回 4 条引用。

0.2 重新从 Dockerfile 构建：首次依赖下载在 PyMuPDF wheel 发生网络 read timeout，因此 Dockerfile 增加 BuildKit pip cache、300 秒 timeout 和 5 次 retry；随后完成干净构建。Compose 首次打开真实 0.1 SQLite 时又暴露“加列前创建新索引”的迁移错误；修复并加入回归后，前后端均为 healthy。当前 `/ready` 返回 schema version 3、queue depth 0 和 ready 的 mock/memory/template；Nginx `/healthz`、Provider 状态与知识库 API 均通过。

真实 API 验收还创建了临时知识库，异步导入内存生成的 DOCX，等待任务成功后通过 SSE 收到 `retrieval.started → retrieval.completed → answer.delta → answer.completed → done`，首条引用来自 DOCX。回环 URL 任务在三次尝试后失败，人工 retry 后取消进入 `cancelled`。清理阶段暴露终态任务外键阻止知识库删除的问题；修复后 `force=true` 可清理文档/终态任务并修复会话范围，活动任务仍返回 `409`，实栈复测通过且只剩默认知识库。

## Browser 人工验收

0.1 加固阶段在应用内 Browser 打开 Docker 实栈并验证：

- 普通模式：提交问题、生成证据回答与当时版本的七阶段 Trace；0.3 已扩展为十阶段。
- 引用：点击首条引用后加载相邻上下文。
- 专家模式：候选池修改为 40 并进入请求 payload。
- 无证据：支付对账问题显示“已安全拒答”、0 条证据、回答决策“拒绝回答”。
- 窄屏：390 × 844 下 `scrollWidth === viewportWidth === 390`；知识库、主区、Inspector 均为单列 374px。
- 错误恢复：后端停止后显示 504、alert 与唯一重试按钮；恢复服务后点击重试，alert 消失并生成回答与 4 条引用。

截图位于 `docs/screenshots/`，均使用仓库示例资料与离线 provider。

第二轮文档取证新增五张 1440 × 900 真实截图：公开 `example.com` URL 导入、引用上下文、质量/引用审计、负反馈 eval draft、504 与 Retry。Browser 同时复核普通/专家模式，并在 390 × 844 下确认 `scrollWidth === clientWidth === 390`。故障注入使用临时 Nginx 2 秒 upstream timeout 与暂停的后端容器；恢复后点击 Retry，错误 alert 归零且 answer status 返回“回答已生成”。

新增的五张技术 SVG 与一张 social preview 均通过 XML/标题/描述/字体/裁切目视检查。`social-preview.png` 实测 1280 × 640、PNG 真格式且小于 1 MB；文档脚本会阻止伪扩展名、漏记清单和错误预览规格进入 CI。

0.2 终验时内置 Browser 连接层仍报 `Cannot redefine property: process`，因此按用户要求转接 Computer Use 操作系统 Chrome。Mac 解锁后，系统 Chrome 实测普通模式流式回答、4 条引用与 Trace；专家参数及无效候选池的即时提示/禁用；跨主题支付问题的“已安全拒答”、0 引用和“拒绝回答”；DevTools Responsive 宽 390、高 844 时知识库、问答和质量区域均保留语义可访问；停止后端后显示 502/504 与 Retry，恢复后点击 Retry 生成回答和 4 条引用。测试只使用离线 provider 和仓库样例。现有 `docs/screenshots/` 仍是此前真实取证，没有用空白的设备画布截图覆盖它们。

0.3 重新使用内置 Browser 验证 Docker 实栈：普通模式恢复含 1 张 Query Asset 的持久会话，十阶段 Trace 显示 3 条 provenance-backed 路径；Graph 页显示 43 nodes / 72 edges 的可缩放 SVG 和等价键盘表格；首条 citation 可跳到聚焦的 heading 元素；专家模式实际切换到 `hybrid_graph`、3 hops 与 table filter；390×844 下 `scrollWidth === clientWidth === 390`。停止后端后页面显示 504、唯一 Retry；恢复后重试使 alert 归零并返回受控拒答。桌面与移动页 console error/warning 均为 0。四张新截图使用 Browser 实际输出的 JPEG 格式保存，未使用伪 `.png` 扩展名。

后续状态机审计复现并修复了运行中任务取消后停留在 `cancelling`、重启后变成不可领取 `queued` 的问题。新增回归验证 Worker 正常取消、过期取消租约恢复、Parser 远端清理、超时清理和“取消不得触发 builtin fallback”。随后增加非破坏性恢复演练，验证 SQLite 快照、外键、schema 和引用对象的安全路径/大小/SHA；完整 pytest 基线由 103 增至 110。

高级 `parser-worker` 本地真实构建已启动，但 Debian 镜像站在下载 28.3 MB `libreoffice-core` 时长时间无进度，限定窗口后主动终止，因此未声称高级 profile 或本地模型解析通过。Dockerfile 随后增加 apt cache、5 次 retry、60 秒下载 timeout，并从完整 `libreoffice` meta package 收窄到 writer/calc/impress；手动 `Advanced parser smoke` workflow 会在 GitHub-hosted runner 检查真实镜像/能力，在带 `rag-parser` 标签的 self-hosted runner 执行可选本地模型解析。默认 Compose 和内置 parser 的结果不受这项外部下载阻塞影响。

## 0.4 Production Local RC 仓库内验收

2026-07-23 在 `codex/release-evidence-1-0` 完成仓库内 contract 与离线回归。宿主机默认 `python3` 没有安装 pytest，因此 Python 测试在按仓库依赖构建的 Python 3.11 容器中运行；Provider 仍固定为 `mock + memory + template`，没有付费调用。

| 项目 | 真实结果 |
| --- | --- |
| 后端 pytest | 179 passed、3 skipped；含 session/CSRF、Redis/outbox/DLQ、S3 生命周期、数据源同步、fetch IP pinning、Prometheus/telemetry scrubber、备份、soak freshness 与 release gate |
| PostgreSQL 实栈 contract | 2 passed；真实 pgvector PostgreSQL 容器验证任务状态和 SQLite→PostgreSQL ID/checksum 对账 |
| 前端 Vitest | 7 files / 22 tests passed |
| `npm run build` | 通过；JS 161.08 kB（gzip 55.20），CSS 32.76 kB（gzip 6.46） |
| Playwright | 14 passed；desktop + mobile，含 session 登录/登出、source sync 与错误恢复 |
| 固定黄金集 | 100 cases；12 项阈值全部通过 |
| 生产 contract | fail-closed 配置、固定镜像、只读应用容器通过；真实 evidence 样例保持 0/13 gates blocked |
| 生产镜像 | Python 3.11 production 依赖完整构建；非 root + read-only smoke 的 `/ready` 和 `/metrics` 通过 |
| S3 归档 smoke | 固定 MinIO + boto3 实际导出 1 个对象、清空 bucket、恢复并逐字节读回 `production-evidence` |

固定集保持 Recall@5 1.0000、MRR 0.9888、首条引用准确率 0.9775、拒答与可回答接受率 1.0000；44 条多模态和 10 条 Graph 专项全部通过。默认 Compose 重建后前后端 healthy，`/ready` 返回 schema version 7，release readiness 在没有部署方私有证据时诚实返回 `blocked`。

`npm run chaos:compose` 的本次结果是安全 dry-run；`npm run restore:production` 只对不存在的 bundle 验证了 fail-fast 路径。没有执行真实破坏性恢复或故障注入，不能把脚本契约记作生产演练完成。完整阻断项见 [1.0 发布证据](release-evidence-1.0.md)。

内置 Browser 打开重建后的真实 Compose 页面，普通模式、专家参数和 source/conversation 区均正常。旧持久文档的 `hybrid-v1` 与当前 `multimodal-v1` 不兼容时，页面如实显示 `needs_rebuild` 和 0 chunks；实际点击“重建全部索引”后恢复为 7 chunks，再次提问得到“回答已生成”、4 条引用和包含 BM25、向量、Graph、MMR、Rerank、引用覆盖率的十阶段 Trace。以 Browser 视口 override 实测 CSS viewport 388px，`scrollWidth === clientWidth === 388`。停止后端后页面显示“请求失败（504）”和“重试连接”；服务恢复后点击重试返回 Provider ready，错误消失且窄屏无溢出。

首轮远端 Security workflow 发现旧固定依赖有 17 条已公布漏洞，且 Trivy Action 使用了不存在的 tag。依照 2026-07-23 官方 PyPI/项目 release 升级 FastAPI 0.139.2、Starlette 1.3.1、python-multipart 0.0.32、PyMuPDF 1.28.0、pytest 9.1.1、python-dotenv 1.2.2，并改用 `aquasecurity/trivy-action@v0.36.0`。新依赖镜像下最新完整后端为 179 passed、3 skipped，Playwright 14 passed；`pip-audit -r backend/requirements-production.txt` 返回 `No known vulnerabilities found`。

修复提交的 Trivy 复扫进一步发现隔离 parser worker 仍单独固定 `python-multipart 0.0.20`。该 worker 已同步升级到 FastAPI 0.139.2 与 python-multipart 0.0.32；这是高级 profile 的独立依赖边界，不应由主后端审计结果替代。

## 远端 CI

0.1 加固分支的 GitHub Actions 已实际跑通。0.2 PR #2 首个功能提交的 push 与 pull_request 两套 backend、docs、frontend、retrieval-eval、docker-compose 共 10 项检查全部通过；后续修复提交仍以对应提交 checks 为准，本地结果不能代替远端 CI。

## 尚不能在本地证明的外部状态

- pgvector、对象存储、外部身份网关和 Sentry 项目：没有提供外部服务或凭据，因此只实现/记录适配边界，未声称已部署。
- OpenAI Responses、OpenAI-compatible Chat 与 Ollama 使用 mock HTTP 契约测试，没有产生付费调用或伪造在线 Provider 结果。

## 0.4 Production Validation 私有实栈

2026-07-23 在 `codex/production-validation-soak` 使用 PostgreSQL/pgvector、MinIO、Redis、ClamAV、隔离 fetch worker 与 Ollama 运行真实本地生产栈。21 组有明确许可证来源产生 200 份非 fixture 文档、12,090 个元素和 5,159 个 768 维向量；200 个 manifest hash、数据库原件、MinIO 对象与 source item 全量对账。

破坏性恢复真实插入数据库哨兵并删除一个 7,007-byte 对象，覆盖恢复后哨兵消失、对象 SHA-256 恢复，文档/资产/元素/任务/评测/向量计数与恢复前一致。随后 API、worker、Redis、PostgreSQL、MinIO 五类 kill/recreate 场景全部保持 200 个唯一文档、200 个唯一幂等任务和 0 个未发布 outbox。演练暴露并修复了来源原件去重误删、部分向量写入、orphan 清理、worker lease heartbeat、错误 worker healthcheck 以及 pgvector 长连接不能跨 PostgreSQL 重启恢复等缺陷。

MinerU 3.4.4 / RAG-Anything 1.3.1 隔离容器对真实 fixture PNG 解析成功并返回 3 个元素；Docling/PaddleOCR 未安装。Ollama 0.32.1 的原生/兼容 embedding 均成功并返回 768 维，`qwen3:8b` 原生 chat、chat-completions 和 Responses 均在 180 秒超时，故 Provider 总验收失败。Sentry 无 DSN、无真实事件，Docker 7.8 GiB 不满足 full self-hosted profile。

14 天 hash-chained soak 于 `2026-07-23T10:25:17Z` 从第一个健康样本开始，历史不回填。到 `2026-07-26T05:27:19Z`，SHA-256 链含 636 个样本和 22 个失败样本；四次真实宿主机/运行时间隔均让连续时间自然重置，最长连续窗口为 81,984 秒，当前窗口从 `2026-07-26T04:57:18Z` 开始。第四次恢复复现并修复 Nginx 缓存已重建 backend 地址的问题；verifier 也新增宿主机时间 freshness 与 state/chain 一致性检查。机器已生成 200 条 draft，但人工确认仍为 0；真实问题来源声明仍为 0。以上数字不会被自动化或 fixture 补齐，项目继续保持 `0.4.0-rc.1`。

## Question-first UI 终验（2026-07-26）

本轮将工作台重构为单一问答画布与两个按需抽屉。简洁模式默认隐藏 Provider、原始检索分值、候选池、系统指标和 1.0 验收记录；上传与数据源位于资料库抽屉，BM25、向量、Graph、MMR、rerank、引用上下文和质量审计保留在调试模式与检索调试抽屉。

| 项目 | 真实结果 |
| --- | --- |
| 前端 Vitest | 7 files / 27 tests passed |
| `npm run build` | 通过；JS 175.57 kB（gzip 60.03），CSS 96.80 kB（gzip 18.54） |
| Playwright | 14/14 passed；desktop Chromium + 390px mobile Chromium |
| 生产前端容器 | 使用原 Production Validation Compose 无损重建；`frontend` 恢复 healthy，未删除任何卷 |
| Browser 实测 | 简洁首页、调试参数、资料库抽屉、检索调试抽屉、来源打开与焦点返回均正常 |
| 真实仅检索 | 在现有本地生产资料上查询 FastAPI 反向代理、转发请求头和 `root_path`，返回 5 条语义相关来源；未勾选真实使用声明，不计入 1.0 的 100 次本人提问 |
| 窄屏 | 390×844 Playwright 视口无横向溢出，底部新对话/资料/调试入口可达 |

截图 `01-workbench-beta.png`、`14-evidence-ledger-mobile.png`、`15-question-first-debug.png` 和 `16-question-first-sources.png` 均来自实际运行页面。测试与截图没有调用付费 API，也没有把本轮 UI 操作回填为人工标注或真实提问证据。
