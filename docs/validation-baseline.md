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

2026-07-14 在 `codex/rag-web-ui-durable-local` 执行全套验收。首次运行的 E2E locator 因任务卡和文档卡同名发生严格定位冲突，按可访问角色修正后 6/6 通过；首次打开真实旧 SQLite 又暴露迁移索引顺序错误，修复后加入 legacy schema 回归。

| 项目 | 真实结果 |
| --- | --- |
| 文档/图片 | 32 Markdown、10 SVG、12 raster 全部通过；secret scan 通过 |
| 后端 pytest | 72 passed；含旧表迁移/备份、KB、任务、DOCX、Provider、SSE、多轮 |
| 前端 Vitest | 4 files / 11 tests passed |
| `npm run build` | 通过；JS 127.01 kB（gzip 44.49），CSS 25.55 kB（gzip 5.33） |
| Demo smoke | 1 passed |
| Playwright | 6 passed；desktop Chromium + 390px mobile Chromium |
| 黄金集 | 40（32 answerable / 8 refusal），五项阈值全部通过 |

黄金集实测：Recall@5 1.0000、MRR 0.9844、首条引用准确率 0.9688、拒答准确率 1.0000、回答接受准确率 1.0000。

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

在应用内 Browser 打开 Docker 实栈并验证：

- 普通模式：提交问题、生成证据回答与七阶段 Trace。
- 引用：点击首条引用后加载相邻上下文。
- 专家模式：候选池修改为 40 并进入请求 payload。
- 无证据：支付对账问题显示“已安全拒答”、0 条证据、回答决策“拒绝回答”。
- 窄屏：390 × 844 下 `scrollWidth === viewportWidth === 390`；知识库、主区、Inspector 均为单列 374px。
- 错误恢复：后端停止后显示 504、alert 与唯一重试按钮；恢复服务后点击重试，alert 消失并生成回答与 4 条引用。

截图位于 `docs/screenshots/`，均使用仓库示例资料与离线 provider。

第二轮文档取证新增五张 1440 × 900 真实截图：公开 `example.com` URL 导入、引用上下文、质量/引用审计、负反馈 eval draft、504 与 Retry。Browser 同时复核普通/专家模式，并在 390 × 844 下确认 `scrollWidth === clientWidth === 390`。故障注入使用临时 Nginx 2 秒 upstream timeout 与暂停的后端容器；恢复后点击 Retry，错误 alert 归零且 answer status 返回“回答已生成”。

新增的五张技术 SVG 与一张 social preview 均通过 XML/标题/描述/字体/裁切目视检查。`social-preview.png` 实测 1280 × 640、PNG 真格式且小于 1 MB；文档脚本会阻止伪扩展名、漏记清单和错误预览规格进入 CI。

0.2 尝试通过内置 Browser 重新打开 Compose 实栈时，Browser 插件连接层报 `Cannot redefine property: process`；按技能要求重连仍失败。随后尝试用 Computer Use 操作本机 Chrome，但 Mac 处于锁屏且无法自动解锁。为避免伪造人工结果，本轮新 UI 的普通/专家/390px/失败重试证据只记录 Playwright 6/6 和 Docker/API 实测，待用户解锁后补一次人工可视复核与新版截图。上面的人工条目和现有截图属于此前 0.1 加固分支的真实取证，不冒充 0.2 新截图。

## 远端 CI

0.1 加固分支的 GitHub Actions 已实际跑通后端、前端/E2E、检索评测和 Docker Compose。0.2 分支推送后以对应提交的 checks 为准；本地结果不能代替远端 CI。

## 尚不能在本地证明的外部状态

- pgvector、对象存储、外部身份网关和 Sentry 项目：没有提供外部服务或凭据，因此只实现/记录适配边界，未声称已部署。
- OpenAI Responses、OpenAI-compatible Chat 与 Ollama 使用 mock HTTP 契约测试，没有产生付费调用或伪造在线 Provider 结果。
