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

## 修改后验收

`npm run verify`：

| 项目 | 结果 |
| --- | --- |
| 后端 pytest | 54 passed |
| 前端 Vitest | 3 files / 8 tests passed |
| `npm run build` | 通过；JS 113.32 kB（gzip 40.42），CSS 23.27 kB（gzip 4.98） |
| Demo smoke | 1 passed |
| Playwright | 4 passed：桌面 + mobile Chromium |
| 黄金集 | 30 条（24 answerable / 6 refusal），全部阈值通过 |

黄金集实测：Recall@5 1.0000、MRR 1.0000、首条引用准确率 1.0000、拒答准确率 1.0000。阈值分别为 0.90 / 0.75 / 0.75 / 0.80。

## Docker Compose

- `docker compose config --quiet` 通过。
- 前端、后端镜像从干净 build context 构建成功。
- `docker compose up --wait --wait-timeout 120 -d` 成功；两个服务均为 healthy。
- `GET :8010/ready` 返回 `mock / memory / template`。
- `GET :5173/healthz` 返回 `ok`。
- `GET :5173/api/documents` 通过 Nginx 代理访问后端。
- 真实停止/重启后端后，SQLite 中 5 份文档自动重建缺失 memory index，问答返回 4 条引用。

## Browser 人工验收

在应用内 Browser 打开 Docker 实栈并验证：

- 普通模式：提交问题、生成证据回答与七阶段 Trace。
- 引用：点击首条引用后加载相邻上下文。
- 专家模式：候选池修改为 40 并进入请求 payload。
- 无证据：支付对账问题显示“已安全拒答”、0 条证据、回答决策“拒绝回答”。
- 窄屏：390 × 844 下 `scrollWidth === viewportWidth === 390`；知识库、主区、Inspector 均为单列 374px。
- 错误恢复：后端停止后显示 504、alert 与唯一重试按钮；恢复服务后点击重试，alert 消失并生成回答与 4 条引用。

截图位于 `docs/screenshots/`，均使用仓库示例资料与离线 provider。

## 尚不能在本地证明的外部状态

- GitHub Actions 远端 run：workflow 已本地等价验证，但需推送分支后才能产生远端 run 与 badge 状态。
- pgvector、对象存储、外部身份网关和 Sentry 项目：没有提供外部服务或凭据，因此只实现/记录适配边界，未声称已部署。
