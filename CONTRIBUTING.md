# Contributing

感谢参与 Personal Multimodal RAG。这个仓库优先接受能提高可解释性、离线可复现、安全性或评测可信度的改动。

## 开发环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
npm ci
npm --prefix frontend ci
cp .env.example .env
npm run dev
```

默认 `.env.example` 不需要任何 Key。开发和测试不要使用真实用户资料。

## 分支与提交

- 从最新 `main` 创建短期分支。
- 一次 PR 解决一个清晰问题，避免顺手重写无关模块。
- 使用能解释意图的提交消息，例如 `fix: preserve index after restart`。
- 不提交 `.env`、数据目录、评测报告、浏览器 trace、真实 DSN 或 Key。

## 开发原则

1. 先写能暴露问题的测试或 eval case。
2. 保留 `mock + memory + template` 离线路径。
3. provider 失败必须可见、可降级、可脱敏。
4. 新检索阶段必须进入 Trace，并说明输入、输出与决策。
5. 新 UI 必须覆盖 loading、empty、error、retry、disabled 和窄屏。
6. 删除或迁移数据的操作必须有恢复和幂等考虑。
7. 不把固定黄金集成绩描述成生产绝对质量。

## 测试

提交前运行：

```bash
npm run verify
git diff --check
```

改动范围与最低覆盖：

| 改动 | 需要补充 |
| --- | --- |
| 上传、URL、认证或日志 | 后端安全/接口测试 |
| 检索、排序、拒答或引用 | 单元测试 + 固定 eval case |
| 页面、组件或状态 | Vitest 组件测试；关键路径补 Playwright |
| Docker、代理或启动 | Compose 健康和代理验证 |
| 配置或 provider | adapter 测试、离线 fallback 与文档 |

更多指标和 case 规范见[测试与评测](docs/testing-and-evaluation.md)。

## 前端约定

- 页面负责信息架构，领域交互放到组件，状态动作放到 composable，网络调用放到 `src/api/`。
- 使用现有 CSS token，不在组件里复制任意颜色和圆角。
- 保留语义标签、键盘焦点、可读错误和 reduced-motion。
- E2E mock 必须精确匹配后端 URL，避免误拦截 Vite `/src/api` 模块。

## 后端约定

- `api/routes.py` 只做路由组合；功能进入 documents、retrieval 或 quality 领域路由。
- 网络和模型能力通过 adapter/service 封装，不让 endpoint 直接拼 provider 请求。
- 所有外部输入都有大小、格式、超时和错误边界。
- 日志使用安全化帮助函数，不记录 credential、URL query 或文档正文。
- 新持久数据要说明 schema、备份、删除和迁移。

## 文档与配图

- README 保持“定位 → 快速启动 → 体验 → 证据 → 深入文档”的顺序。
- 复杂关系优先使用 Mermaid 或 `docs/assets/` 中的 SVG。
- 产品行为必须配真实截图；概念主视觉不能代替验收证据。
- 图片提供准确 alt text，避免只用“截图”作为说明。
- 修改命令、端口、阈值或环境变量时同步更新相关专题文档。

## Pull Request 清单

- [ ] 说明问题、方案、取舍和不在范围内的内容。
- [ ] 列出实际运行的测试与结果。
- [ ] 新测试不调用付费 API。
- [ ] UI 改动包含桌面、390px 和错误状态证据。
- [ ] 检索改动附指标对比和失败 case。
- [ ] 安全相关改动说明威胁模型和剩余风险。
- [ ] README、OpenAPI/配置和已知边界已同步。

## 安全报告

安全漏洞不要通过公开 PR 或 issue 首次披露。请遵循 [SECURITY.md](SECURITY.md) 的私密报告流程。
