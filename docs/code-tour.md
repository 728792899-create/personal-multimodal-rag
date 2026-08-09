# 代码导览

这份导览帮助评审者从一次浏览器请求进入代码，而不是按目录逐个猜职责。项目保持稳定的 API/结构定义，同时把前端单体与后端组合根拆成可独立测试的领域模块。

![请求从浏览器经过 Nginx、中间件、领域路由、服务和模型提供方返回](assets/request-lifecycle.svg)

## 一次请求如何流动

1. `frontend/src/pages/WorkbenchPage.vue` 组织问题优先的单画布、资料/调试抽屉与普通/调试模式。
2. 领域组件触发 `frontend/src/composables/useWorkbench.ts` 中的动作。
3. `frontend/src/api/client.ts` 统一处理基础 URL、超时、中止、错误负载和请求 ID；documents、ingestion、knowledgeBases、conversations、providers、retrieval、quality 模块保持领域边界。
4. Docker 模式下 Nginx 把 `/api` 代理到 FastAPI；本地 Vite 使用同一路径语义。
5. `backend/app/main.py` 注册 CORS、请求保护中间件、健康检查与 API 组合根。
6. `backend/app/middleware/request_guards.py` 处理可选 bearer、进程限流、`Retry-After` 和 `X-Request-ID`。
7. `backend/app/api/routes.py` 只组合 documents、ingestion、knowledge-bases、conversations、providers、retrieval、quality 领域路由。
8. 服务层执行任务入库、检索、流式回答、引用审计或质量计算；`core/store.py` 组装适配器并由生命周期管理本地工作进程。
9. 模型提供方异常经过脱敏后回退或形成可读错误；响应沿原路径返回，前端进入成功、错误、取消或重试状态。

## 前端地图

| 路径 | 关注点 | 适合从这里修改 |
| --- | --- | --- |
| `src/pages/WorkbenchPage.vue` | 页面布局与模式切换 | 信息架构、响应式组合 |
| `src/components/knowledge/` | 上传、URL、文档列表 | 入库体验与文档状态 |
| `src/components/query/` | 提问与专家参数 | 请求参数与禁用状态 |
| `src/components/answer/` | 回答、引用、反馈 | 可信度与失败闭环 |
| `src/components/inspector/` | 检索追踪、指标、质量 | 可解释性与审计视图 |
| `src/components/RetrievalTrace.vue` | 十阶段流程卡 | 查询/BM25/向量/图谱/父级上下文/MMR/重排/拒答/引用诊断 |
| `src/components/GraphExplorer.vue` | 图谱 SVG + 等价表格 | 来源路径的视觉和键盘审查 |
| `src/composables/useWorkbench.ts` | 领域状态与动作 | 加载、取消、重试、数据刷新 |
| `src/composables/useKnowledgeBases.ts` | KB 列表、选择与创建 | 知识范围 |
| `src/composables/useIngestionJobs.ts` | 任务轮询、取消与重试 | 可恢复入库 |
| `src/composables/useConversations.ts` | SSE、会话和消息 | 流式/停止/最终审计 |
| `src/composables/useProviderStatus.ts` | 只读模型提供方诊断 | 配置引导，不保存密钥 |
| `src/api/client.ts` | 网络边界 | 超时、错误映射、请求 ID |
| `src/api/*.ts` | 领域 API | 端点和结构定义对接 |

![前端空闲、进行中、成功、错误、取消和重试状态机](assets/frontend-state-machine.svg)

每个异步动作使用独立进行中/错误状态，避免上传阻塞问答或一次失败清空其他区域。键盘、焦点、窄屏和减弱动态效果属于组件验收条件，不是页面最后补丁。

## 后端地图

| 路径 | 职责 | 关键边界 |
| --- | --- | --- |
| `api/routers/documents.py` | 上传、URL、删除、重建 | 类型/大小/SSRF/源文件清理 |
| `api/routers/retrieval.py` | 搜索、问答、上下文、历史 | 参数归一化、检索追踪、引用上下文 |
| `api/routers/quality.py` | 反馈、评测、指标、卡片 | 草稿与黄金集分离 |
| `api/routers/ingestion.py` | 文件/URL 入队与任务 API | 暂存、幂等、取消/重试 |
| `api/routers/knowledge_bases.py` | 知识库 CRUD | 默认库与强制删除 |
| `api/routers/conversations.py` | 会话 CRUD 和 SSE | 事件顺序、持久消息、断连 |
| `api/routers/providers.py` | 模型提供方状态 | 只读、脱敏能力诊断 |
| `services/document_processor.py` | 解析、分块、元数据 | 解析器/OCR 的输入边界 |
| `services/retriever.py` | BM25、向量、融合、MMR | 候选与排序可观测性 |
| `services/rag_engine.py` | 问答编排与无答案门 | 回答/拒答决策 |
| `services/answer_generator.py` | 模板/Responses 适配器 | 外部回答模型提供方回退 |
| `services/citation_audit.py` | 覆盖率与无支撑主张 | 规则审计的已知局限 |
| `services/document_registry.py` | SQLite 注册表 | 当前单工作区数据边界 |
| `services/ingestion_jobs.py` | 本地工作进程 | SQLite 认领、租约恢复、阶段取消 |
| `services/provider_clients.py` | 聊天/Ollama HTTP 适配器 | JSON/SSE/NDJSON 契约 |
| `services/vectorstore.py` | 内存/Chroma/pgvector 适配器 | 持久化和维度兼容 |

## 三条典型路径

### 上传

`POST /api/ingestions/file` → 安全文件名 → 分块写入和大小限制 → 文件签名/DOCX ZIP → 幂等任务 → 工作进程认领 → 解析/OCR → 分块 → BM25/向量 → SQLite 注册表 → 任务完成。

任何失败都会清理尚未接受的临时文件；删除只允许移除受控上传目录中的直接文件，不跟随任意路径。

### 提问

`POST /api/conversations/{id}/messages:stream` → 本地上下文 → 知识库隔离 → 混合检索 → MMR/重排 → 证据门 → 模板/Responses/聊天/Ollama 流式输出 → 引用审计 → 消息完成 → 界面。旧 `/api/ask` 保持兼容。

检索追踪保留每阶段候选数、耗时、回退与最终决策。重排只能重新排序已有候选，不能修复前序漏召回。

### 反馈

`POST /api/feedback` → 关联历史快照 → 保存评分/失败类型 → 生成评测草稿 → 更新反馈统计。草稿通过 `GET /api/eval/drafts` 查看，但只有经过人工审查的固定案例才进入 CI 黄金集。

## 扩展点

- 新嵌入：实现现有嵌入接口，并在配置工厂中显式注册；先补尺寸、批处理、超时和回退测试。
- 新向量库：实现 add/search/delete/existing chunk 语义；验证重启加载和删除一致性。
- 新重排器：保持输入候选与检索追踪结构定义；加入排序单测和黄金集回归。
- 多工作区：先把授权与 `workspace_id` 注入所有查询/存储，再迁移数据；不能只在前端增加筛选。
- 分布式索引：保留当前 `IndexJob` 状态机和幂等键，把本地 SQLite 认领换成外部队列/工作进程；多实例前补重复投递、死信和故障转移测试。

进一步阅读：[架构说明](architecture.md)、[数据模型](data-model.md)、[安全威胁模型](security-model.md)、[测试与评测](testing-and-evaluation.md)。
