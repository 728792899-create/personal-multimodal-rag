# Release Checklist

## 仓库与 PR 已验证（0.3 当前提交）

- [x] `git diff --check` 无空白错误。
- [x] `npm run lint:secrets` 确认没有提交真实 Key、DSN、私有 URL 或用户资料。
- [x] Python/npm 依赖文件与前端 lockfile 已提交，默认测试不下载模型或调用付费 API。
- [x] 上传白名单、大小、空文件、签名、像素、动画、失败清理和知识库边界测试通过。
- [x] URL SSRF、重定向、内容类型、超时和大小限制测试通过。
- [x] 协作取消、过期租约、三次重试、Parser 超时/清理和取消不 fallback 测试通过。

## 自动质量门

- [x] `npm run lint:docs` 与 `npm run lint:secrets`
- [x] `npm test`、`npm run build` 与 `npm run test:demo`
- [x] `npm run eval:retrieval`、`eval:multimodal` 与 `eval:graph`
- [x] `npm run test:parser-contract` 与 `npm run test:asset-security`
- [x] `npm run test:e2e`
- [x] 100 条固定集的 12 项指标均达到 `eval/thresholds.json`。
- [x] Browser 人工检查普通、专家、390px、图片提问、Graph、精确引用、拒答与错误恢复。

## 本地容器与数据

- [x] `docker compose up --build --wait -d`
- [x] 前后端 healthcheck 均 healthy。
- [x] 从前端域名访问 `/api/documents` 成功。
- [x] 上传、级联删除、服务重启、索引恢复与 504 Retry 通过。
- [x] GitHub Actions 的 docs、backend、frontend、retrieval-eval、multimodal-eval、graph-eval、parser-contract、asset-security、docker-compose 全绿。

## 部署负责人必须完成

- [ ] 生产环境已配置 TLS、身份网关、可信代理和高熵 `API_AUTH_TOKEN`，且密钥由服务端注入。
- [ ] 生产备份/恢复演练覆盖数据库和对象存储。
- [ ] 数据保留、删除与日志脱敏策略已由部署负责人确认。
- [ ] 下载并抽查当前提交的 eval/Playwright artifact。
- [ ] 在目标环境完成 Advanced parser smoke；未启用高级 profile 时记录为“不适用”，不得伪造通过。
- [ ] 镜像使用不可变 tag/digest，记录迁移顺序。
- [ ] 回滚版本与数据库兼容性已确认。
- [ ] 发布后检查 `/health`、`/ready`、错误率、p95 延迟和拒答率。
- [ ] 失败时回滚镜像；索引任务可重复执行且不会删除原始对象。

仓库已经更新版本、CHANGELOG、已知边界和回滚说明；上面的未勾选项依赖真实部署环境、凭据或发布权限，因此不能由离线 CI 代替。
