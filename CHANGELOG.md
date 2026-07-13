# Changelog

本项目遵循面向 Beta 的语义化版本记录。当前尚未发布正式稳定 API。

## Unreleased

### Added

- 作品集级 README 主视觉、系统全景、七阶段检索、质量闭环与部署拓扑。
- 产品巡游、检索原理、API、配置、测试评测、运维、FAQ、路线图和文档中心。
- 贡献指南、视觉资产来源与 Browser 截图维护说明。

## 0.1.0-beta

### Added

- PDF、Markdown、文本、图片 OCR 与公开 URL 导入。
- BM25、向量检索、融合、MMR、rerank、无证据拒答和引用审计。
- 普通模式与专家模式、检索 Trace、知识卡片、反馈和 eval draft。
- 离线 mock/template/memory 模式与 Docker Compose 一键启动。
- pytest、Vitest、Playwright、固定黄金集、GitHub Actions 与健康检查。
- 上传/URL 安全边界、请求 ID、限流、脱敏日志和可选 Sentry。

### Known limitations

- 默认 hash embedding 和 template answer 只用于离线演示。
- 当前是单实例、单 workspace Beta；生产外部服务尚需部署方接入。
- 固定黄金集规模较小，不代表真实开放域质量。
