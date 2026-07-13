# Release Checklist

## 代码与安全

- [ ] `git diff --check` 无空白错误。
- [ ] `git grep` 确认没有真实 Key、DSN、私有 URL 或用户资料。
- [ ] 依赖审计已检查，新增依赖有锁文件。
- [ ] 上传白名单、大小、空文件、签名、清理测试通过。
- [ ] URL SSRF、重定向、内容类型、超时和大小限制测试通过。
- [ ] 生产环境已配置 TLS、身份网关、可信代理和高熵 `API_AUTH_TOKEN`（如直接暴露 API）。

## 质量门

- [ ] `npm test`
- [ ] `npm run build`
- [ ] `npm run test:demo`
- [ ] `npm run eval:retrieval`
- [ ] `npm run test:e2e`
- [ ] 评测报告中四项关键指标均达到 `eval/thresholds.json`。
- [ ] Browser 人工检查普通、专家、390px、拒答与错误恢复。

## 容器与数据

- [ ] `docker compose up --build --wait -d`
- [ ] 前后端 healthcheck 均 healthy。
- [ ] 从前端域名访问 `/api/documents` 成功。
- [ ] 上传、删除与服务重启后索引恢复通过。
- [ ] 生产备份/恢复演练覆盖数据库和对象存储。
- [ ] 数据保留、删除与日志脱敏策略已由部署负责人确认。

## 发布与回滚

- [ ] 更新版本、CHANGELOG/Release notes 和已知边界。
- [ ] GitHub Actions 四个 job 全绿，下载并抽查 eval/Playwright artifact。
- [ ] 镜像使用不可变 tag/digest，记录迁移顺序。
- [ ] 回滚版本与数据库兼容性已确认。
- [ ] 发布后检查 `/health`、`/ready`、错误率、p95 延迟和拒答率。
- [ ] 失败时回滚镜像；索引任务可重复执行且不会删除原始对象。
