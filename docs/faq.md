# 常见问题

## 为什么没有 API Key 也能回答？

默认使用 deterministic hash embedding、memory vector store 和 template answer。它能完整走通索引、混合检索、拒答、引用和评测，但不代表真实语义模型质量。

## 默认模式会联网吗？

上传和本地问答不会。只有主动导入 URL 才会访问该公开地址；配置 Responses/OpenAI-compatible/Ollama provider 后也会访问指定 API。测试命令会强制清空 Key 并使用离线 provider。

## 支持哪些文件？

PDF、DOCX、Markdown、纯文本、PNG、JPG/JPEG。DOCX 保留标题、段落和表格文本；图片 OCR 需要 Tesseract，Docker 后端镜像已包含运行时。当前不做图片语义理解、通用 PDF 表格恢复、音频或视频解析。

## 为什么一个 RAG 项目需要拒答？

向量库总能返回“最相似”的内容，但最相似不一定相关。如果资料不包含答案，安全结果应该是说明证据不足，而不是用弱匹配生成流畅结论。

## Trace 是给最终用户看的吗？

普通模式展示精简结论，专家模式展示完整阶段。它同时服务开发调试、评测分析和作品集讲解；真实面向非技术用户的产品可以进一步收起分数细节。

## Recall@5 为 1.0 是否代表生产质量完美？

不是。当前是 100 条固定、脱敏回归集，虽覆盖图像、表格、公式、版面/OCR、Graph 多跳和冲突/拒答，仍只证明这些 case 在当前离线实现上没有退化。生产前需要真实领域资料、困难负样本、冲突证据和人工抽样。

## 可以直接开启 pgvector 做多团队 SaaS 吗？

不可以。adapter 不等于完整多租户架构。还需要 workspace schema、服务端授权过滤、对象存储边界、后台任务、分布式限流、审计和越权测试。

## 为什么不用 LangChain？

项目希望直接展示解析、检索、融合、MMR、拒答和引用审计的工程实现，减少框架内部行为对作品集可解释性的遮挡。生产项目仍可按团队标准引入框架，但要保留 Trace 和回归门。

## 如何切换真实 OpenAI-compatible provider？

参考[配置指南](configuration.md)。建议一次只替换一个 adapter，使用新索引版本并运行固定评测。production 默认禁用模板降级；不要把 Key 写入 Git 或 `VITE_*` 环境变量。

## 知识库是否等于多租户 workspace？

不是。知识库会在检索前隔离资料，适合单用户整理主题；它没有用户身份、成员权限或服务端 workspace claim，不能作为团队间安全边界。

## 索引任务在重启后会丢失吗？

任务保存在 SQLite，running 任务带租约；进程中断后过期租约会重新排队，最多自动尝试三次。当前只保证单实例本地恢复，多节点仍需外部队列。

## 为什么服务重启后文档还在但 memory index 不持久？

文档内容和 metadata 存在 SQLite registry。启动时会检查 vector store 并只补建缺失文档，所以 memory 模式可以恢复检索；持久 store 已有 chunk 时不会重复 embedding。

## 如何报告安全问题？

不要开公开 issue 或附带真实资料。使用 GitHub Private Security Advisory / Report a vulnerability，细节见 [SECURITY.md](../SECURITY.md)。
