# Personal Multimodal RAG · 证据工作台

**中文** · [English overview](README.en.md)

[![CI](https://github.com/728792899-create/personal-multimodal-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/728792899-create/personal-multimodal-rag/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-0f766e.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-2563eb.svg)](backend/requirements.txt)
[![Node 22+](https://img.shields.io/badge/Node-22%2B-0f766e.svg)](frontend/package.json)
[![Offline First](https://img.shields.io/badge/default-offline%20%2F%20zero--key-7c3aed.svg)](.env.example)

![多模态资料经过混合检索、证据门和引用审计形成可信回答](docs/assets/multimodal-rag-hero.png)

**从 PDF、网页、图片与笔记，到可解释、可拒答、可量化回归的证据链。**

[快速启动](#5-分钟离线启动) · [端到端案例](docs/case-study.md) · [产品巡游](docs/product-tour.md) · [文档中心](docs/README.md) · [代码导览](docs/code-tour.md) · [评测结果](docs/evaluation-results.md) · [安全模型](docs/security-model.md)

面向单用户/小团队 Beta 的本地优先多模态 RAG 工作台。它不只展示“上传并问答”，还把 BM25、向量召回、融合去重、MMR、Rerank、拒答决策和引用覆盖率组织成可理解、可回归的证据链。

默认使用 deterministic hash embedding、内存向量库和模板回答：**无需真实 API Key、不会调用付费 API**。PDF、DOCX、Markdown、文本、图片 OCR、URL 导入、持久会话、引用上下文、质量审计、反馈评测和专家参数均保留。

正在交付的 **0.3 Multimodal Intelligence** 将文档拆成可审查的 text、heading、image、table、equation、code 元素；原件与内嵌资源进入内容寻址对象存储，chunk 保留元素 provenance。默认内置解析器仍然零下载；MinerU、Docling、PaddleOCR 只通过隔离的可选 Compose profile 接入。设计取舍见 [RAG-Anything 固定提交对比审查](docs/comparative-review-rag-anything.md)。

## 一分钟看懂

![系统从资料输入到质量回归的完整地图](docs/assets/system-overview.svg)

| 默认体验 | 可信度机制 | 工程证据 | 生产边界 |
| --- | --- | --- | --- |
| 零 Key、离线可运行 | 无证据拒答 | 73 个后端测试 | 可选认证与 Sentry |
| 多知识库、DOCX 与 URL | 七阶段检索 Trace | 11 个前端测试 | Chroma / pgvector adapter |
| 持久会话与流式回答 | 引用上下文与覆盖审计 | 6 个 Browser E2E | 外部任务队列/对象存储方案 |
| 可恢复索引任务 | 反馈 → eval draft | 40 条黄金回归 case | 本地 Demo 永不依赖外部服务 |

这个仓库刻意同时展示三件事：**RAG 能力、工程可靠性、产品可信度**。如果只想快速体验，从[产品巡游](docs/product-tour.md)开始；如果要审查实现，阅读[架构](docs/architecture.md)和[检索原理](docs/retrieval-explained.md)；如果准备部署，直接查看[配置](docs/configuration.md)、[运维手册](docs/operations-runbook.md)与[生产适配](docs/production-adapters.md)。

## 适合用来做什么

- 在本地管理个人或小团队资料，并获得带引用回答。
- 演示一个可解释、可测试、能安全拒答的 RAG 工程作品集。
- 用固定黄金集回归 Recall@5、MRR、首条引用准确率和拒答准确率。
- 在同一界面比较普通模式与专家模式，定位召回、排序、生成或引用问题。

它目前不是多租户 SaaS，也没有宣称默认 hash embedding 具备生产语义检索质量。生产扩展边界见 [生产适配方案](docs/production-adapters.md) 与 [已知边界](docs/known-limitations.md)。

## 能力地图

| 领域 | 已实现 | 默认离线 | 可选增强 |
| --- | --- | :---: | --- |
| 输入 | PDF、DOCX、Markdown、TXT、PNG/JPEG、公开 URL | ✓ | Tesseract OCR |
| 处理 | SQLite 任务、租约恢复、去重、重试/取消、版本兼容 | ✓ | 分布式队列待接入 |
| 检索 | 知识库隔离、BM25、vector、融合、MMR、rerank | ✓ | local/OpenAI/Ollama embedding、Chroma、pgvector |
| 回答 | 持久会话、SSE、模板/Responses/chat/Ollama adapter | ✓ | 外部 Provider 人工验证 |
| 可信度 | no-answer gate、引用、相邻上下文、citation audit | ✓ | NLI/LLM judge 待规划 |
| 质量 | 反馈、eval draft、黄金集、Recall@K、MRR、引用/拒答 | ✓ | 真实流量抽样待规划 |
| 交付 | Nginx、FastAPI、Compose、healthcheck、GitHub Actions | ✓ | 云端基础设施由部署方接入 |
| 安全 | 上传边界、SSRF、防泄漏日志、限流、Bearer token | ✓ | OIDC、Redis、AV scan 待部署 |

## 5 分钟离线启动

要求：Python 3.11+、Node.js 22+。OCR 可选依赖由 Docker 镜像自动提供。

```bash
git clone https://github.com/728792899-create/personal-multimodal-rag.git
cd personal-multimodal-rag

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt

npm ci
npm --prefix frontend ci
cp .env.example .env
npm run dev
```

另开终端导入仓库内脱敏示例资料：

```bash
source .venv/bin/activate
npm run demo:bootstrap
```

打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。`.env.example` 已默认配置：

```text
EMBEDDING_PROVIDER=mock
VECTOR_STORE=memory
ANSWER_PROVIDER=template
QUERY_REWRITE_PROVIDER=none
```

因此没有任何 Key 也能完成上传、索引、检索、回答、引用、拒答和评测流程。

## Docker Compose 一键启动

Docker 路径不要求先创建 `.env`：

```bash
docker compose up --build --wait -d
npm run demo:bootstrap
```

- 工作台：[http://127.0.0.1:5173](http://127.0.0.1:5173)
- 后端健康检查：[http://127.0.0.1:8010/health](http://127.0.0.1:8010/health)
- Provider 就绪检查：[http://127.0.0.1:8010/ready](http://127.0.0.1:8010/ready)

前端使用生产 Nginx 镜像，并将 `/api` 反向代理到 FastAPI；前后端都配置了容器健康检查。停止服务：

```bash
docker compose down
```

![离线演示、持久单用户与小团队 Beta 的部署演进](docs/assets/deployment-modes.svg)

默认 Compose 对应 Level 1。Level 2/3 不是隐藏开关：它们需要明确的索引迁移、持久服务、认证和运维步骤，详见[配置指南](docs/configuration.md)与[生产适配方案](docs/production-adapters.md)。

## 可复现验收

所有命令都强制使用离线 provider：

```bash
npm test                 # 后端 pytest + 前端 Vitest
npm run lint:docs        # 相对链接、图片 alt 与 SVG 可访问性
npm run build            # vue-tsc + Vite production build
npm run test:demo        # 端到端 API smoke
npm run eval:retrieval   # 40 条固定黄金集 + 五项阈值
npm run test:e2e         # Chromium 桌面 + 390px 级移动视图
```

一次运行全部验收：

```bash
npm run verify
```

当前本地验收证据见 [验证基线](docs/validation-baseline.md)。评测失败会生成可读报告到 `eval/reports/latest.md`；CI 会始终上传报告 artifact。

![40 条固定黄金集的指标实际值、门槛与 case 分布](docs/assets/evaluation-scorecard.svg)

| 检查 | 当前本地结果 | CI 门槛 |
| --- | ---: | ---: |
| 后端测试 | 73 passed | 全部通过 |
| 前端单元/组件 | 13 passed | 全部通过 |
| Browser E2E | 6 passed | 桌面与移动全部通过 |
| Recall@5 | 1.0000 | ≥ 0.90 |
| MRR | 0.9844 | ≥ 0.75 |
| 首条引用准确率 | 0.9688 | ≥ 0.75 |
| 拒答准确率 | 1.0000 | ≥ 0.80 |
| 回答接受准确率 | 1.0000 | ≥ 0.85 |

> 上表是仓库内固定、脱敏、小规模黄金集的回归结果，用于发现代码退化，不代表开放域或真实业务语料上的绝对质量。

完整的数据集构成、判定方式与限制见[固定黄金集评测结果](docs/evaluation-results.md)。

## 核心体验

### 界面图集

| 工作台 | 可解释回答 | 窄屏拒答 |
| --- | --- | --- |
| ![普通模式三栏工作台](docs/screenshots/01-workbench-beta.png) | ![回答、引用与七阶段 Trace](docs/screenshots/02-grounded-trace.png) | ![390px 专家模式与无证据拒答](docs/screenshots/03-mobile-expert-refusal.png) |
| 管理资料、提问与系统概览 | 检查 BM25、向量、排序和引用 | 无横向溢出，保留完整状态 |

| 上传与 URL 导入 | 引用相邻上下文 | 质量与引用审计 |
| --- | --- | --- |
| ![上传、URL 表单和索引资料](docs/screenshots/04-ingestion-url.png) | ![展开引用及前后 chunk](docs/screenshots/05-citation-context.png) | ![检索质量、引用覆盖和系统指标](docs/screenshots/06-quality-dashboard.png) |
| 两条入库路径状态独立 | 从片段返回完整证据 | 诊断召回、排序和覆盖 |

| 反馈生成 eval draft | 504 错误与重试 |
| --- | --- |
| ![负反馈和自动生成的评测草稿](docs/screenshots/07-feedback-eval-draft.png) | ![保留最后成功结果的 504 错误与重试入口](docs/screenshots/08-error-retry.png) |
| 失败进入人工审查闭环 | 请求 ID、错误说明和恢复动作 |

完整的逐步说明见[端到端案例](docs/case-study.md)与[产品巡游](docs/product-tour.md)。

### 普通模式

- 创建/切换知识库，上传 PDF、DOCX、Markdown、文本、PNG/JPEG，或导入公开 URL。
- 在任务中心查看排队、分块、嵌入、写入、失败、取消与重试状态。
- 选择知识库或指定文档范围，在持久会话中获得流式、证据约束回答。
- 查看引用片段、相邻上下文、置信度和引用覆盖率。
- 对无证据问题明确拒答，不把向量噪声包装成结论。
- 负反馈一键生成 eval draft。

### 专家模式

- 调整 `search_mode`、profile、Top K、candidate K、向量权重、MMR λ 与最低分。
- 比较 BM25-only、Vector-only、Hybrid、Hybrid + Rerank。
- 查看七阶段 Trace：BM25 → 向量 → 融合去重 → MMR → Rerank → 回答/拒答 → 引用审计。
- 查看 fallback、query rewrite、耗时、文档质量、操作日志和评测草稿。

设计评审工作文件：[Figma · Personal Multimodal RAG Beta](https://www.figma.com/design/r2oFc38SGqh8QPvFykEEfq)。前端实现以同一组语义 token、间距、圆角、焦点和状态规范为准。

## 架构

![系统分层、数据流、拒答与评测闭环](docs/assets/system-overview.svg)

![Browser、Nginx、中间件、领域路由、服务和 provider 的请求生命周期](docs/assets/request-lifecycle.svg)

<details>
<summary>展开 Mermaid 实现链路</summary>

```mermaid
flowchart LR
  UI["Vue 工作台"] --> API["FastAPI 领域路由"]
  API --> INGEST["异步上传 / URL / OCR / 去重"]
  INGEST --> JOBS["SQLite Index Jobs"]
  INGEST --> REG["SQLite Registry"]
  INGEST --> INDEX["BM25 + Vector Adapter"]
  API --> ENGINE["RAG Engine"]
  ENGINE --> RET["BM25 + Vector + MMR + Rerank"]
  RET --> GATE["No-answer Gate"]
  GATE --> GEN["Template / Responses"]
  GEN --> AUDIT["Citation Audit"]
  AUDIT --> UI
  UI --> FEEDBACK["Feedback → Eval Draft"]
  FEEDBACK --> GOLDEN["Golden Regression"]
```

</details>

前端已经从单体 `App.vue` 拆成页面、领域组件、`useWorkbench` composable 与 `api/{client,documents,retrieval,quality}`；后端原 `routes.py` 现在只做路由组合，文档、检索、质量路由分别维护。详见[代码导览](docs/code-tour.md)、[架构说明](docs/architecture.md)与[SQLite 数据模型](docs/data-model.md)。

### 七阶段检索

![BM25、向量、融合、MMR、重排、拒答和引用审计](docs/assets/retrieval-pipeline.svg)

阶段视图同时显示候选数量、分数、耗时、fallback、拒答理由和引用覆盖，让“答案不对”可以继续拆解成召回、融合、多样性、排序、决策或引用问题。计算与诊断方法见[检索与可信回答](docs/retrieval-explained.md)。

## 安全与稳定性

- 上传扩展名白名单、20 MB 上限、空文件拒绝、路径清理、唯一落盘名、PDF/图片 magic-byte 和 DOCX ZIP-bomb 校验。
- URL 仅允许 HTTP(S)，禁止嵌入凭据，初始/重定向/最终地址都执行 SSRF 校验，并限制内容类型、字节数和超时。
- API 支持可选 Bearer Token、进程内限流、`Retry-After` 和请求 ID。
- 前端请求有超时、取消、Abort 语义、可读错误、请求 ID 与重试入口。
- 日志会清理 Authorization、token、password、secret、URL query/fragment。
- Sentry 仅在显式提供 DSN 且安装可选依赖时启用；默认关闭 PII 与 request body。
- SQLite 任务以租约恢复进程中断工作，最多三次自动尝试；内容哈希与索引版本组成幂等键。
- `memory` 向量库重启时会从 SQLite 文档注册表重建缺失索引；维度/模型/索引版本不兼容的文档被标记 `needs_rebuild`，不混用向量。

安全策略与漏洞报告见 [SECURITY.md](SECURITY.md)。

![浏览器、API、不可信输入、外部 provider 和存储的安全信任边界](docs/assets/security-boundaries.svg)

具体威胁、已实现控制和剩余风险见[安全威胁模型](docs/security-model.md)。

## OpenAI 可选接法

默认运行不需要 OpenAI。若显式选择真实 provider：

- Responses 使用 `POST /v1/responses` 和 `store:false`；流式消费 `response.output_text.delta`、`response.completed` 与 `error`，会话事实保存在本地 SQLite。
- Embedding 使用批量 `input` 与 `encoding_format=float`；`dimensions` 只在配置非零且模型支持时发送。
- 网络客户端有超时且错误文本经过脱敏；只有 local/test 显式允许模板回退，production 默认以安全 `503` 失败。

配置示例见 `.env.example`。实现按 [OpenAI Streaming Responses](https://developers.openai.com/api/docs/guides/streaming-responses)、[Conversation state](https://developers.openai.com/api/docs/guides/conversation-state) 和 [Embeddings API](https://developers.openai.com/api/reference/resources/embeddings/methods/create) 校对。

## 目录

```text
backend/app/
  api/routes.py              # 路由组合根
  api/routers/               # documents / ingestion / KB / conversations / providers / quality
  middleware/                # auth / rate limit / request id
  services/                  # ingest / retrieval / answer / audit / adapters
frontend/
  src/pages/                 # WorkbenchPage
  src/components/            # knowledge / query / answer / inspector / trace
  src/composables/           # useWorkbench + context
  src/api/                   # client + 领域 API + types
  e2e/                       # Playwright 关键路径
eval/                        # cases + thresholds
samples/demo-documents/      # 公开脱敏样例
docs/                        # 架构、部署、排障、发布与证据
```

## CI 与发布

GitHub Actions 分五个 job：

1. 文档相对链接、图片 alt 与 SVG 可访问性检查。
2. 后端测试（强制 mock/memory/template）。
3. 前端单元测试、构建和 Chromium E2E。
4. 黄金集阈值回归，并上传 Markdown/JSON 报告。
5. Docker Compose 构建、健康等待和前端代理 API 验证。

远端 GitHub Actions 已实际验证这些 job；badge 反映默认分支最近一次 workflow 状态。发布前仍需逐项执行 [Release Checklist](docs/release-checklist.md)，并抽查评测和 Playwright artifact。

![用户反馈、黄金集、报告和 CI 的质量循环](docs/assets/evaluation-loop.svg)

## 更多文档

| 我想要…… | 从这里开始 | 继续深入 |
| --- | --- | --- |
| 看完整使用案例 | [端到端案例](docs/case-study.md) | [产品巡游](docs/product-tour.md) |
| 快速理解产品 | [产品巡游](docs/product-tour.md) | [演示脚本](docs/demo-script.md) |
| 审查代码结构 | [代码导览](docs/code-tour.md) | [数据模型](docs/data-model.md) |
| 审查检索质量 | [检索原理](docs/retrieval-explained.md) | [测试与评测](docs/testing-and-evaluation.md) |
| 查看固定成绩 | [评测结果](docs/evaluation-results.md) | [验证基线](docs/validation-baseline.md) |
| 集成后端 | [API 使用指南](docs/api-reference.md) | [架构说明](docs/architecture.md) |
| 切换 provider | [配置指南](docs/configuration.md) | [生产适配方案](docs/production-adapters.md) |
| 运行和排障 | [运维手册](docs/operations-runbook.md) | [故障排查](docs/troubleshooting.md) |
| 评估上线条件 | [已知边界](docs/known-limitations.md) | [Release Checklist](docs/release-checklist.md) |
| 查看真实证据 | [验证基线](docs/validation-baseline.md) | [项目复盘](docs/project-retrospective.md) |
| 参与开发 | [贡献指南](CONTRIBUTING.md) | [路线图](docs/roadmap.md) |
| 解决常见疑问 | [FAQ](docs/faq.md) | [安全策略](SECURITY.md) |
| 审查威胁边界 | [安全模型](docs/security-model.md) | [生产适配](docs/production-adapters.md) |

## 关键设计取舍

- **离线优先，不是离线限定。** 默认路径保证任何审查者都能复现，真实模型通过 adapter 接入。
- **拒答优先于流畅。** 没有证据时给出缺口，比生成看似完整的答案更符合知识工具定位。
- **Trace 服务于决策。** 不展示无组织的 debug JSON，而是按检索因果顺序组织信息。
- **回归指标互相制衡。** Recall 防漏召回，MRR 防排序退化，引用防错来源，拒答防无依据扩张。
- **本地边界不冒充多租户。** Bearer token、SQLite 和进程限流适合 Beta；真正 workspace 隔离需要 schema 与服务端授权。
- **真实截图与概念配图分工。** 截图证明产品状态，SVG/主视觉解释系统关系，两者都不能代替自动化测试。

## 参与与安全

欢迎提交可复现的 bug、评测 case、可访问性改进和 adapter 增强。开始前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题不要公开披露或附带真实资料，请使用 GitHub Private Security Advisory，流程见 [SECURITY.md](SECURITY.md)。

## License

[MIT](LICENSE)
