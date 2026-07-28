# 验证基线与最终证据

执行日期：2026-07-14（Asia/Shanghai）。所有测试都清空 OpenAI/回答/改写密钥，并使用 `mock + memory + template + no rewrite`。没有调用付费 API。

## 修改前真实基线

| 项目 | 结果 |
| --- | --- |
| 后端测试 | 35 项通过，5 个 PyMuPDF/SWIG 弃用警告 |
| 前端生产构建 | 通过；JS 113.29 kB（gzip 38.72），CSS 19.10 kB（gzip 4.38） |
| 演示冒烟测试 | 1 项通过 |
| 旧检索评测 | 30 条、单一 `rag-notes.md`；Recall@5 1.0000、MRR 0.8333、引用精确率 1.0000 |
| 真实本地启动 | `/health` 正常；5 份样例完成索引；创建 4 条 eval draft |

旧评测只有一份来源文档，引用指标偏乐观；该结果仅作基线，不作为最终质量声明。

## 0.1 加固分支验收（历史）

`npm run verify`：

| 项目 | 结果 |
| --- | --- |
| 文档检查 | 30 个 Markdown、10 个 SVG、12 个光栅图片通过链接、替代文字、格式、清单与可访问性校验 |
| 后端 pytest | 54 项通过 |
| 前端 Vitest | 3 个文件 / 8 项测试通过 |
| `npm run build` | 通过；JS 113.32 kB（gzip 40.42），CSS 23.27 kB（gzip 4.98） |
| 演示冒烟测试 | 1 项通过 |
| Playwright | 4 项通过：桌面 + 移动端 Chromium |
| 黄金集 | 30 条（24 条可回答 / 6 条拒答），全部阈值通过 |

黄金集实测：Recall@5 1.0000、MRR 1.0000、首条引用准确率 1.0000、拒答准确率 1.0000。阈值分别为 0.90 / 0.75 / 0.75 / 0.80。

## 0.2 持久本地版当前验收

2026-07-14 在 `codex/rag-web-ui-durable-local` 执行全套验收。首次运行的端到端定位器因任务卡和文档卡同名发生严格定位冲突，按可访问角色修正后 6/6 通过；首次打开真实旧 SQLite 又暴露迁移索引顺序错误，修复后加入旧架构回归。系统 Chrome 终验进一步发现 FastAPI 校验数组显示为 `[object Object]`，以及无条件拼接会话历史会让跨主题问题绕过拒答门；两项均先复现、修复并加入回归。

| 项目 | 真实结果 |
| --- | --- |
| 文档/图片 | 32 个 Markdown、10 个 SVG、12 个光栅图片全部通过；密钥扫描通过 |
| 后端 pytest | 73 项通过；含旧表迁移/备份、知识库、任务、DOCX、模型提供方、SSE、多轮与跨主题拒答 |
| 前端 Vitest | 4 个文件 / 13 项测试通过 |
| `npm run build` | 通过；JS 128.37 kB（gzip 45.00），CSS 25.66 kB（gzip 5.35） |
| 演示冒烟测试 | 1 项通过 |
| Playwright | 6 项通过；桌面 Chromium + 390px 移动端 Chromium |
| 黄金集 | 40 条（32 条可回答 / 8 条拒答），五项阈值全部通过 |

黄金集实测：Recall@5 1.0000、MRR 0.9844、首条引用准确率 0.9688、拒答准确率 1.0000、回答接受准确率 1.0000。

## 0.3 图谱检索第二阶段验收

2026-07-15 在 `codex/graph-retrieval` 执行 `npm run verify`。所有模型提供方测试继续使用模板回答或 `httpx.MockTransport`，密钥被显式清空，没有外部模型请求。

| 项目 | 真实结果 |
| --- | --- |
| 文档/图片 | 33 个 Markdown、10 个 SVG、12 个光栅图片通过；密钥扫描检查 210 个候选 |
| 后端 pytest | 98 项通过；新增 v4→v5 迁移、图谱来源证明/知识库隔离、视觉契约、重试/熔断、回退观测与 LightRAG 白名单 |
| 前端 Vitest | 4 个文件 / 13 项测试通过 |
| `npm run build` | 通过；JS 128.65 kB（gzip 45.09），CSS 25.66 kB（gzip 5.35） |
| 演示冒烟测试 | 1 项通过 |
| Playwright | 6 项通过；桌面 Chromium + 390px 移动端 Chromium |
| 黄金集 | 40 条（32 条可回答 / 8 条拒答），五项原有阈值全部通过 |

黄金集保持 Recall@5 1.0000、MRR 0.9844、首条引用准确率 0.9688、拒答准确率 1.0000、回答接受准确率 1.0000。Graph 专项当前由 13 个确定性后端契约覆盖；100 条多模态/graph 固定集和 Browser 图谱 UI 验收属于第三阶段，尚未提前声称完成。

## 0.3 多模态问答与评测第三阶段验收

2026-07-15 在 `codex/multimodal-query-ui-eval` 执行专项与全链路验证。测试配置继续强制 `mock + memory + template`，没有付费 API 请求。

| 项目 | 真实结果 |
| --- | --- |
| 文档/图片 | 33 个 Markdown、10 个 SVG、16 个光栅图片通过；密钥扫描检查 244 个候选 |
| 后端 pytest | 110 项通过；查询附件、附件 SSE、协作取消终态、解析器取消/超时，以及 SQLite + 对象存储隔离恢复均有契约测试 |
| 前端 Vitest | 5 个文件 / 15 项测试通过；新增图片附件与图谱 SVG/等价表格 |
| `npm run build` | 通过；JS 145.54 kB（gzip 50.26），CSS 29.78 kB（gzip 5.99） |
| Playwright | 8 项通过；桌面 + 390px 移动端，含图片提问、图谱控件与键盘表格 |
| 查询附件测试集 | 12 个真实 PNG，全部 640×360、非动画、小于 1 MB |
| 黄金集 | 100 条（89 条可回答 / 11 条拒答），12 项阈值全部通过 |
| 多模态专项 | 44 个案例；模态 Recall@5、表格单元、图注、公式均为 1.0000 |
| 图谱专项 | 10 个案例；路径精确率、证据覆盖率、多跳 Recall@5 均为 1.0000 |

全集实测：Recall@5 1.0000、MRR 0.9888、首条引用 0.9775、拒答 1.0000、可回答接受 1.0000。详细案例行位于 `eval/reports/latest.md`；上述数据只是固定仓库测试集回归信号。

Docker 实栈重新构建后，`/ready` 返回架构版本 5 与 `mock / memory / template`。真实 API 创建临时知识库，异步导入图谱测试集到 `succeeded`，上传 640×360 PNG 后按序收到 `query.enrichment.started → query.enrichment.completed → retrieval.started → retrieval.completed → answer.delta → answer.completed → done`；`hybrid_graph` 返回 4 个种子、3 条路径和 1 个证据元素。

## Docker Compose

- `docker compose config --quiet` 通过。
- 前端、后端镜像从干净构建上下文构建成功。
- `docker compose up --wait --wait-timeout 120 -d` 成功；两个服务均为健康状态。
- `GET :8010/ready` 返回 `mock / memory / template`。
- `GET :5173/healthz` 返回 `ok`。
- `GET :5173/api/documents` 通过 Nginx 代理访问后端。
- 真实停止/重启后端后，SQLite 中 5 份文档自动重建缺失内存索引，问答返回 4 条引用。

0.2 重新从 Dockerfile 构建：首次依赖下载在 PyMuPDF wheel 发生网络读取超时，因此 Dockerfile 增加 BuildKit pip 缓存、300 秒超时和 5 次重试；随后完成干净构建。Compose 首次打开真实 0.1 SQLite 时又暴露“加列前创建新索引”的迁移错误；修复并加入回归后，前后端均为健康状态。当前 `/ready` 返回架构版本 3、队列深度 0 和就绪的 mock/memory/template；Nginx `/healthz`、模型提供方状态与知识库 API 均通过。

真实 API 验收还创建了临时知识库，异步导入内存生成的 DOCX，等待任务成功后通过 SSE 收到 `retrieval.started → retrieval.completed → answer.delta → answer.completed → done`，首条引用来自 DOCX。回环 URL 任务在三次尝试后失败，人工重试后取消进入 `cancelled`。清理阶段暴露终态任务外键阻止知识库删除的问题；修复后 `force=true` 可清理文档/终态任务并修复会话范围，活动任务仍返回 `409`，实栈复测通过且只剩默认知识库。

## 浏览器人工验收

0.1 加固阶段在应用内浏览器打开 Docker 实栈并验证：

- 普通模式：提交问题、生成证据回答与当时版本的七阶段检索追踪；0.3 已扩展为十阶段。
- 引用：点击首条引用后加载相邻上下文。
- 专家模式：候选池修改为 40 并进入请求负载。
- 无证据：支付对账问题显示“已安全拒答”、0 条证据、回答决策“拒绝回答”。
- 窄屏：390 × 844 下 `scrollWidth === viewportWidth === 390`；知识库、主区、Inspector 均为单列 374px。
- 错误恢复：后端停止后显示 504、提示与唯一重试按钮；恢复服务后点击重试，提示消失并生成回答与 4 条引用。

截图位于 `docs/screenshots/`，均使用仓库示例资料与离线模型提供方。

第二轮文档取证新增五张 1440 × 900 真实截图：公开 `example.com` URL 导入、引用上下文、质量/引用审计、负反馈评测草稿、504 与重试。浏览器同时复核普通/专家模式，并在 390 × 844 下确认 `scrollWidth === clientWidth === 390`。故障注入使用临时 Nginx 2 秒上游超时与暂停的后端容器；恢复后点击重试，错误提示归零且回答状态返回“回答已生成”。

新增的五张技术 SVG 与一张 social preview 均通过 XML/标题/描述/字体/裁切目视检查。`social-preview.png` 实测 1280 × 640、PNG 真格式且小于 1 MB；文档脚本会阻止伪扩展名、漏记清单和错误预览规格进入 CI。

0.2 终验时内置浏览器连接层仍报 `Cannot redefine property: process`，因此按用户要求转接 Computer Use 操作系统 Chrome。Mac 解锁后，系统 Chrome 实测普通模式流式回答、4 条引用与检索追踪；专家参数及无效候选池的即时提示/禁用；跨主题支付问题的“已安全拒答”、0 引用和“拒绝回答”；DevTools 响应式宽 390、高 844 时知识库、问答和质量区域均保留语义可访问；停止后端后显示 502/504 与重试，恢复后点击重试生成回答和 4 条引用。测试只使用离线模型提供方和仓库样例。现有 `docs/screenshots/` 仍是此前真实取证，没有用空白的设备画布截图覆盖它们。

0.3 重新使用内置浏览器验证 Docker 实栈：普通模式恢复含 1 张查询附件的持久会话，十阶段检索追踪显示 3 条带来源证明的路径；图谱页显示 43 个节点 / 72 条边的可缩放 SVG 和等价键盘表格；首条引用可跳到聚焦的标题元素；专家模式实际切换到 `hybrid_graph`、3 跳与表格过滤；390×844 下 `scrollWidth === clientWidth === 390`。停止后端后页面显示 504、唯一重试；恢复后重试使提示归零并返回受控拒答。桌面与移动页控制台错误/警告均为 0。四张新截图使用浏览器实际输出的 JPEG 格式保存，未使用伪 `.png` 扩展名。

后续状态机审计复现并修复了运行中任务取消后停留在 `cancelling`、重启后变成不可领取 `queued` 的问题。新增回归验证工作进程正常取消、过期取消租约恢复、解析器远端清理、超时清理和“取消不得触发内置回退”。随后增加非破坏性恢复演练，验证 SQLite 快照、外键、架构和引用对象的安全路径/大小/SHA；完整 pytest 基线由 103 增至 110。

高级 `parser-worker` 本地真实构建已启动，但 Debian 镜像站在下载 28.3 MB `libreoffice-core` 时长时间无进度，限定窗口后主动终止，因此未声称高级配置或本地模型解析通过。Dockerfile 随后增加 apt 缓存、5 次重试、60 秒下载超时，并从完整 `libreoffice` 元包收窄到 writer/calc/impress；手动 `Advanced parser smoke` 工作流会在 GitHub 托管运行器检查真实镜像/能力，在带 `rag-parser` 标签的自托管运行器执行可选本地模型解析。默认 Compose 和内置解析器的结果不受这项外部下载阻塞影响。

## 0.4 本地生产 RC 仓库内验收

2026-07-23 在 `codex/release-evidence-1-0` 完成仓库内契约与离线回归。宿主机默认 `python3` 没有安装 pytest，因此 Python 测试在按仓库依赖构建的 Python 3.11 容器中运行；模型提供方仍固定为 `mock + memory + template`，没有付费调用。

| 项目 | 真实结果 |
| --- | --- |
| 后端 pytest | 179 项通过、3 项跳过；含会话/CSRF、Redis/发件箱/死信队列、S3 生命周期、数据源同步、抓取 IP 固定、Prometheus/遥测脱敏器、备份、稳定性新鲜度与发布门 |
| PostgreSQL 实栈契约 | 2 项通过；真实 pgvector PostgreSQL 容器验证任务状态和 SQLite→PostgreSQL ID/校验和对账 |
| 前端 Vitest | 7 个文件 / 22 项测试通过 |
| `npm run build` | 通过；JS 161.08 kB（gzip 55.20），CSS 32.76 kB（gzip 6.46） |
| Playwright | 14 项通过；桌面 + 移动端，含会话登录/登出、数据源同步与错误恢复 |
| 固定黄金集 | 100 个案例；12 项阈值全部通过 |
| 生产契约 | 故障关闭配置、固定镜像、只读应用容器通过；真实证据样例保持 0/13 发布门阻断 |
| 生产镜像 | Python 3.11 生产依赖完整构建；非 root + 只读冒烟测试的 `/ready` 和 `/metrics` 通过 |
| S3 归档冒烟测试 | 固定 MinIO + boto3 实际导出 1 个对象、清空存储桶、恢复并逐字节读回 `production-evidence` |

固定集保持 Recall@5 1.0000、MRR 0.9888、首条引用准确率 0.9775、拒答与可回答接受率 1.0000；44 条多模态和 10 条图谱专项全部通过。默认 Compose 重建后前后端健康，`/ready` 返回架构版本 7，发布就绪状态在没有部署方私有证据时诚实返回 `blocked`。

`npm run chaos:compose` 的本次结果是安全试运行；`npm run restore:production` 只对不存在的归档包验证了快速失败路径。没有执行真实破坏性恢复或故障注入，不能把脚本契约记作生产演练完成。完整阻断项见 [1.0 发布证据](release-evidence-1.0.md)。

内置浏览器打开重建后的真实 Compose 页面，普通模式、专家参数和数据源/会话区均正常。旧持久文档的 `hybrid-v1` 与当前 `multimodal-v1` 不兼容时，页面如实显示 `needs_rebuild` 和 0 个分块；实际点击“重建全部索引”后恢复为 7 个分块，再次提问得到“回答已生成”、4 条引用和包含 BM25、向量、图谱、MMR、重排、引用覆盖率的十阶段检索追踪。以浏览器视口覆盖实测 CSS 视口 388px，`scrollWidth === clientWidth === 388`。停止后端后页面显示“请求失败（504）”和“重试连接”；服务恢复后点击重试返回模型提供方就绪，错误消失且窄屏无溢出。

首轮远端安全工作流发现旧固定依赖有 17 条已公布漏洞，且 Trivy Action 使用了不存在的标签。依照 2026-07-23 官方 PyPI/项目发布升级 FastAPI 0.139.2、Starlette 1.3.1、python-multipart 0.0.32、PyMuPDF 1.28.0、pytest 9.1.1、python-dotenv 1.2.2，并改用 `aquasecurity/trivy-action@v0.36.0`。新依赖镜像下最新完整后端为 179 项通过、3 项跳过，Playwright 14 项通过；`pip-audit -r backend/requirements-production.txt` 返回 `No known vulnerabilities found`。

修复提交的 Trivy 复扫进一步发现隔离解析工作进程仍单独固定 `python-multipart 0.0.20`。该工作进程已同步升级到 FastAPI 0.139.2 与 python-multipart 0.0.32；这是高级配置的独立依赖边界，不应由主后端审计结果替代。

## 远端 CI

截至 2026-07-29，PR #15 的最新功能提交已实际通过 push 与 pull request 两套工作流共 30 项检查，覆盖 backend、docs、frontend、retrieval-eval、multimodal-eval、graph-eval、parser-contract、asset-security、docker-compose、CodeQL、依赖审计、生产契约、Trivy 与 SBOM。后续提交仍以对应提交 checks 为准，本地结果不能代替远端 CI。

## 尚不能在本地证明的外部状态

- pgvector、对象存储、外部身份网关和 Sentry 项目：没有提供外部服务或凭据，因此只实现/记录适配边界，未声称已部署。
- OpenAI Responses、OpenAI-compatible Chat 与 Ollama 使用 mock HTTP 契约测试，没有产生付费调用或伪造在线 Provider 结果。

## 0.4 Production Validation 私有实栈

2026-07-23 在 `codex/production-validation-soak` 使用 PostgreSQL/pgvector、MinIO、Redis、ClamAV、隔离 fetch worker 与 Ollama 运行真实本地生产栈。21 组有明确许可证来源产生 200 份非 fixture 文档、12,090 个元素和 5,159 个 768 维向量；200 个 manifest hash、数据库原件、MinIO 对象与 source item 全量对账。

破坏性恢复真实插入数据库哨兵并删除一个 7,007-byte 对象，覆盖恢复后哨兵消失、对象 SHA-256 恢复，文档/资产/元素/任务/评测/向量计数与恢复前一致。随后 API、worker、Redis、PostgreSQL、MinIO 五类 kill/recreate 场景全部保持 200 个唯一文档、200 个唯一幂等任务和 0 个未发布 outbox。演练暴露并修复了来源原件去重误删、部分向量写入、orphan 清理、worker lease heartbeat、错误 worker healthcheck 以及 pgvector 长连接不能跨 PostgreSQL 重启恢复等缺陷。

MinerU 3.4.4 / RAG-Anything 1.3.1 隔离容器对真实 fixture PNG 解析成功并返回 3 个元素；Docling/PaddleOCR 未安装。Ollama 0.32.1 的原生/兼容 embedding 均成功并返回 768 维，`qwen3:8b` 原生 chat、chat-completions 和 Responses 均在 180 秒超时，故 Provider 总验收失败。Sentry 无 DSN、无真实事件，Docker 7.8 GiB 不满足 full self-hosted profile。

14 天 hash-chained soak 于 `2026-07-23T10:25:17Z` 从第一个健康样本开始，历史不回填。到 `2026-07-28T17:47:03Z`，SHA-256 链含 1,170 个样本和 27 个失败样本，状态与链一致且宿主机时间新鲜；真实宿主机/运行时间隔均让连续时间自然重置，最长连续窗口为 81,984 秒。当前窗口自 `2026-07-28T16:26:46Z` 开始，已记录 4,817 秒。Production Compose 9/9 服务健康，Redis Streams `pending=0`、`lag=0`，2 条 DLQ 为保留的历史审计记录。机器已生成 200 条 draft，但人工确认仍为 0；真实问题来源声明仍为 0。以上数字不会被自动化或 fixture 补齐，项目继续保持 `0.4.0-rc.1`。

## Question-first UI 终验（2026-07-26 至 2026-07-29）

本轮将工作台重构为单一问答画布与两个按需抽屉。简洁模式默认隐藏 Provider、原始检索分值、候选池、系统指标和 1.0 验收记录；上传与数据源位于资料库抽屉，BM25、向量、Graph、MMR、rerank、引用上下文和质量审计保留在调试模式与检索调试抽屉。

| 项目 | 真实结果 |
| --- | --- |
| 前端 Vitest | 11 files / 62 tests passed |
| `npm run build` | TypeScript 检查与 Vite 生产构建通过 |
| Playwright | 14/14 passed；desktop Chromium + 390px mobile Chromium |
| 生产前端容器 | 使用原 Production Validation Compose 无损重建；`frontend` 恢复 healthy，未删除任何卷 |
| Browser 实测 | 简洁首页、调试参数、资料库抽屉、检索调试抽屉、来源打开与焦点返回均正常 |
| 真实仅检索 | 在现有本地生产资料上查询 FastAPI 反向代理、转发请求头和 `root_path`，返回 5 条语义相关来源；未勾选真实使用声明，不计入 1.0 的 100 次本人提问 |
| 窄屏 | 390×844 Playwright 视口无横向溢出，底部新对话/资料/调试入口可达 |

截图 `01-workbench-beta.png`、`14-evidence-ledger-mobile.png`、`15-question-first-debug.png` 和 `16-question-first-sources.png` 均来自实际运行页面。测试与截图没有调用付费 API，也没有把本轮 UI 操作回填为人工标注或真实提问证据。

2026-07-28 至 29 又完成 DeepSeek 官方连接面板与会话恢复验收：真实 `GET /models` 连通检查不生成内容；成功 SSE 的最终事件不会再被短暂滞后的持久层读取降级为“未完成”。桌面与 390px Browser 验证覆盖连接、清除、无效凭据恢复和刷新恢复；密钥未进入截图、响应、浏览器持久化或 Git。
