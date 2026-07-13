# Visual assets

本目录保存概念配图和代码原生架构图。它们用于解释系统，不替代真实截图、测试报告或部署证据。

| 文件 | 类型 | 用途 | 来源 |
| --- | --- | --- | --- |
| `multimodal-rag-hero.png` | 1806×871 PNG | README 宽幅主视觉 | Codex 内置 image generation |
| `system-overview.svg` | SVG | 输入、入库、检索、回答和改进全景 | 仓库内代码原生绘制 |
| `retrieval-pipeline.svg` | SVG | 七阶段检索 Trace | 仓库内代码原生绘制 |
| `evaluation-loop.svg` | SVG | 反馈到 CI 的质量闭环 | 仓库内代码原生绘制 |
| `deployment-modes.svg` | SVG | 三种部署成熟度 | 仓库内代码原生绘制 |

## 主视觉生成说明

主视觉使用内置 image generation 生成，核心 prompt：

> Wide GitHub README hero for an open-source multimodal RAG evidence workbench: PDF, web page, image and notes flow through distinct lexical retrieval, vector retrieval, ranking, evidence gating and citation checking stages into a grounded answer card. Deep navy, teal, cyan and violet; premium restrained 3D/vector style; no people, logos, readable text or watermark.

生成图是概念说明，不表示真实 UI。真实界面见 `../screenshots/`。

## 修改规范

- SVG 保持自包含，不加载外部字体、脚本或远端图片。
- 每张 SVG 提供 `<title>`、`<desc>`、`role="img"` 与 `aria-labelledby`。
- 颜色与前端语义 token 保持接近，但不把图表 CSS 当作前端设计系统来源。
- 修改流程或阈值时同步检查所有引用这张图的文档。
- 新生成图片必须记录来源和用途，不得包含真实用户资料或第三方商标。

校验：

```bash
xmllint --noout docs/assets/*.svg
file docs/assets/*
```
