# 演示脚本

## 准备

按 README 完成依赖安装，然后：

```bash
cp .env.example .env
npm run dev
```

另开终端：

```bash
npm run demo:bootstrap
```

## 8 分钟路径

1. 打开 `http://127.0.0.1:5173`，确认 5 份公开样例和 6 个 chunk。
2. 普通模式提问：`固定评测集关注哪些关键指标？`
3. 指出回答、置信度、引用数量、来源数量和覆盖率处于同一信任摘要。
4. 点击首条引用，展示相邻上下文，不只展示截断 snippet。
5. 查看 Trace 七阶段，解释 BM25 与向量并行召回、融合、MMR、Rerank、回答决策和引用覆盖。
6. 切换专家模式，把 candidate K 改为 40，对比 keyword/semantic/hybrid profile。
7. 提问：`支付系统的每日对账差异如何自动冲正？`，展示“已安全拒答”、0 引用与拒答阶段。
8. 回到有效回答，点击“需要改进并生成评测草稿”，在评测 tab 查看 draft。
9. 展示 `npm run eval:retrieval` 的固定阈值报告与 CI workflow。

## 演示时必须说明

- 当前是离线 hash/template 模式，没有调用付费 API。
- 固定黄金集用于回归，不代表开放域质量。
- 真实 pgvector、对象存储、身份网关和 Sentry 需要外部服务，仓库只给出适配边界与人工步骤。
