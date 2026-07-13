# Browser screenshots

这里的图片来自本地运行中的真实工作台，用于证明主要交互状态。示例资料均来自仓库 `samples/demo-documents/`，不包含用户隐私数据。

| 文件 | 视口 | 验证内容 |
| --- | --- | --- |
| `01-workbench-beta.png` | 1280×720 | 普通模式三栏信息架构、知识库与提问入口 |
| `02-grounded-trace.png` | 1440×900 | 带引用回答、七阶段 Trace 与质量检查 |
| `03-mobile-expert-refusal.png` | 390×844 | 专家模式、无证据拒答和窄屏无横向溢出 |
| `01-workbench.jpg` | 1280×720 | 早期工作台基线截图，保留用于前后对照 |
| `02-grounded-answer.jpg` | 1280×720 | 早期带引用回答截图，保留用于前后对照 |

## 更新截图

1. 使用离线 provider 启动 Docker Compose。
2. 运行 `npm run demo:bootstrap`。
3. 只使用仓库脱敏问题和样例资料。
4. 分别覆盖普通模式、专家 Trace、拒答、390px 与错误恢复。
5. 截图前检查页面没有 API Key、私有 URL、真实路径或系统通知。
6. 更新本清单和 README alt text。

截图是人工证据，不能替代 Playwright。界面行为变化时必须先更新自动化测试，再更新截图。
