# 持续数据源与增量同步

0.4 RC 在手动上传之外增加三种可持续使用的数据源：允许目录、URL 列表和 RSS/Atom。连接器只负责发现与读取，所有新内容仍复用原来的对象存储、解析、enrichment、Graph、索引版本、引用与拒答链路。

## 数据模型

- `sources` 保存知识库、连接器类型、公开配置和启用状态。
- `source_items` 使用 `(source_id, external_id)` 唯一约束，记录内容 hash、ETag、Last-Modified、索引文档和删除候选状态。
- `sync_runs` 记录 discovered、unchanged、updated、failed、partial、empty result 和 deletion candidate 数量。

索引仍由 `index_jobs` 执行。同步发现更新时，原文先进入内容寻址对象存储，再创建带 `source_item_id` 的幂等索引任务。Worker 成功后把文档回填到来源条目；更新替换旧文档时会清理旧向量、元素、图谱和无人引用的对象。

## 允许目录

浏览器不能提交任意服务器路径。服务端通过 `SOURCE_ROOTS` 配置一个或多个只读根目录：

```text
SOURCE_ROOTS=/srv/rag/notes:/srv/rag/research
```

API 只返回不可逆 root ID 和目录名；创建数据源时只接受 root ID 与相对路径。绝对路径、`..`、逃逸根目录的 symlink、超大文件和不支持的扩展名都会被拒绝。Compose 默认把 `${SOURCE_DIRECTORY:-./data/sources}` 只读挂载到 `/sources`。

## URL 列表与 Feed

- URL 列表会去重 URL，再获取受 SSRF 和大小上限保护的正文。
- RSS/Atom 使用 feed entry `id/guid` 作为首选稳定 external ID，缺失时使用链接。
- Feed 请求携带保存的 ETag 与 Last-Modified；304 不创建任务，也不推进删除判断。
- XML 拒绝 DTD 和 entity declaration，并受响应字节和条目数量限制。

每个条目的正文 hash 决定是否需要重新索引。部分条目失败时成功条目仍可入队，但本次 run 标记 `partial`。

## 删除保护

来源条目不会因一次同步缺失就消失：

1. 只有完整成功且非空的同步才能累加 missing count。
2. 空 Feed、304、获取失败或部分失败不会累加。
3. 条目连续两次完整同步仍缺失，才标记 `deletion_candidate`。
4. 用户在工作台明确确认后，系统才删除来源条目、文档、元素、chunk、向量、图谱和无人引用对象。

删除“订阅配置”本身不会自动删除已经索引的文档，避免误操作扩大影响范围。

## API

```text
GET    /api/sources
POST   /api/sources
GET    /api/sources/{id}
PATCH  /api/sources/{id}
DELETE /api/sources/{id}
POST   /api/sources/{id}/sync
POST   /api/sources/{id}/deletions:confirm
GET    /api/sync-runs
GET    /api/sync-runs/{id}
POST   /api/sync-runs/{id}/retry
```

API 进程在重启时把遗留 `running` run 标记为可读的 `failed`，用户可安全重试；条目内容 hash 与 index job 幂等键保证重复同步不会生成重复文档。

## Markdown 导出

以下接口输出带引用的 UTF-8 Markdown attachment：

```text
GET /api/exports/history/{id}.md
GET /api/exports/conversations/{id}.md
GET /api/exports/knowledge-cards/{id}.md
```

导出包含问题、回答、引用文件、页码、证据片段和可用审计值。浏览器不保存 API Key，下载仍受当前 session 认证边界保护；其他写操作继续要求 CSRF Token。
