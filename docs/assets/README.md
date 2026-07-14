# Visual assets

本目录保存概念配图和代码原生架构图。它们用于解释系统，不替代真实截图、测试报告或部署证据。

| 文件 | 类型 | 用途 | 来源 |
| --- | --- | --- | --- |
| `multimodal-rag-hero.png` | 1806×871 PNG | README 宽幅主视觉 | Codex 内置 image generation |
| `system-overview.svg` | SVG | 输入、入库、检索、回答和改进全景 | 仓库内代码原生绘制 |
| `retrieval-pipeline.svg` | SVG | 七阶段检索 Trace | 仓库内代码原生绘制 |
| `evaluation-loop.svg` | SVG | 反馈到 CI 的质量闭环 | 仓库内代码原生绘制 |
| `deployment-modes.svg` | SVG | 三种部署成熟度 | 仓库内代码原生绘制 |
| `request-lifecycle.svg` | 1440×660 SVG | Browser 到 response 的请求生命周期 | 仓库内代码原生绘制 |
| `data-model.svg` | 1440×780 SVG | 当前 SQLite/vector 数据与生产迁移边界 | 仓库内代码原生绘制 |
| `security-boundaries.svg` | 1440×760 SVG | 不可信输入和外部服务的信任边界 | 仓库内代码原生绘制 |
| `frontend-state-machine.svg` | 1440×560 SVG | 前端异步动作的可恢复状态 | 仓库内代码原生绘制 |
| `evaluation-scorecard.svg` | 1440×760 SVG | 30 条固定黄金集成绩卡 | 仓库内代码原生绘制 |
| `social-preview.svg` | 1280×640 SVG | GitHub social preview 的确定性源文件 | 仓库内代码原生绘制 |
| `social-preview.png` | 1280×640 PNG | GitHub Settings 上传与英文 README 预览 | 从同名 SVG 确定性导出 |

## 主视觉生成说明

主视觉是仓库唯一的生成式概念插画，使用内置 image generation 生成，核心 prompt：

> Wide GitHub README hero for an open-source multimodal RAG evidence workbench: PDF, web page, image and notes flow through distinct lexical retrieval, vector retrieval, ranking, evidence gating and citation checking stages into a grounded answer card. Deep navy, teal, cyan and violet; premium restrained 3D/vector style; no people, logos, readable text or watermark.

生成图是概念说明，不表示真实 UI。真实界面见 `../screenshots/`。

## 修改规范

- SVG 保持自包含，不加载外部字体、脚本或远端图片。
- 每张 SVG 提供 `<title>`、`<desc>`、`role="img"` 与 `aria-labelledby`。
- 颜色与前端语义 token 保持接近，但不把图表 CSS 当作前端设计系统来源。
- 修改流程或阈值时同步检查所有引用这张图的文档。
- 新生成图片必须记录来源和用途，不得包含真实用户资料或第三方商标。
- `social-preview.png` 必须保持 1280×640 且小于 1 MB；修改 SVG 后重新导出并运行文档校验。

校验：

```bash
xmllint --noout docs/assets/*.svg
file docs/assets/*
npm run lint:docs
```
