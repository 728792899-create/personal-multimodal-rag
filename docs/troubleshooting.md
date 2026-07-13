# 故障排查

## 页面显示“请求失败”

1. 检查 `curl http://127.0.0.1:8010/ready`。
2. Docker 模式检查 `docker compose ps` 与 `docker compose logs backend`。
3. 记录 UI 中的请求 ID；不要复制 Authorization 或文档原文到公共 issue。
4. 服务恢复后直接点击错误条中的“重试”。

若 Nginx 返回 502/504，通常是后端未就绪或超时；前端会保留上一次成功回答，不会用错误响应覆盖它。

## 全新克隆无法启动

- 确认 Python 3.11+ 与 Node 22+。
- 根目录和前端是两个 npm package，必须同时执行 `npm ci` 与 `npm --prefix frontend ci`。
- 确认 Python 虚拟环境中已执行 `python -m pip install -r backend/requirements.txt`。
- 不要为了离线 Demo 安装 `requirements-optional.txt`。

## 重启后能看到文档但检索为空

当前版本会在 `memory` store 启动时从 SQLite 文档注册表重建缺失 chunk。若仍为空：

- 检查上传文件仍在 `data/uploads`；
- 查看 `/api/operations` 是否有解析/索引失败；
- 在 UI 点击“重建全部索引”；
- 确认容器挂载了 `./data:/app/data`。

## Chroma 维度不匹配

不同 embedding 模型/维度不能写入同一 collection。为新模型设置新的 `CHROMA_PATH` 与 `CHROMA_COLLECTION`，重新索引并验证后再切换。不要直接删除唯一生产副本。

## URL 导入被拒绝

- 只支持 HTTP(S) 的公开地址。
- 回环、内网、链路本地、嵌入用户名密码、二进制 content type、超大响应和超时都会被拒绝。
- `RAG_ALLOW_PRIVATE_URLS=1` 会扩大 SSRF 风险，只能在网络隔离且目标受信时启用。

## 图片没有 OCR 文本

本地安装 Tesseract 与中英文语言包，并确保 `tesseract` 在 `PATH`。Docker 镜像已经包含 `tesseract-ocr`、`chi-sim` 和 `pytesseract`。

## 评测失败

运行 `npm run eval:retrieval`，打开 `eval/reports/latest.md` 的“需要处理”。不要先下调阈值：先确认失败属于索引缺失、排序退化、引用来源错误还是拒答门失效。新增修复必须补固定 case。

## 真实 OpenAI provider 失败

- 默认 Demo 不需要 Key；先切回 `mock/template` 判断是否为外部 provider 问题。
- Responses base URL 应指向 API 根（代码会拼接 `/responses`）；Embedding adapter 使用 OpenAI SDK 的 embeddings resource。
- 核对模型是否支持自定义 embedding dimensions。
- 错误会经过脱敏并降级；不要把完整 Key 或带 query 的 URL 放入日志。
