# Browser screenshots

这里的图片来自本地运行中的真实工作台，用于证明主要交互状态。示例资料均来自仓库 `samples/demo-documents/`，不包含用户隐私数据。

| 文件 | 视口 | 验证内容 |
| --- | --- | --- |
| `01-workbench-beta.png` | 1440×900 | Question-first 简洁模式、单一问答画布与按需工具入口 |
| `02-grounded-trace.png` | 1440×900 | 早期带引用回答、七阶段 Trace 与质量检查，保留作对照 |
| `03-mobile-expert-refusal.png` | 390×844 | 专家模式、无证据拒答和窄屏无横向溢出 |
| `01-workbench.jpg` | 1280×720 | 早期工作台基线截图，保留用于前后对照 |
| `02-grounded-answer.jpg` | 1280×720 | 早期带引用回答截图，保留用于前后对照 |
| `04-ingestion-url.png` | 1440×900 | 上传入口、URL 导入与已索引资料 |
| `05-citation-context.png` | 1440×900 | 引用详情与相邻 chunk 上下文 |
| `06-quality-dashboard.png` | 1440×900 | 检索 Trace、引用审计与系统质量指标 |
| `07-feedback-eval-draft.png` | 1440×900 | 负反馈与自动生成的 eval draft |
| `08-error-retry.png` | 1440×900 | API 504、请求 ID、保留成功状态与 retry |
| `09-multimodal-query-trace.jpg` | 1280×720 | 图片证据入口、持久多模态会话与回答状态 |
| `10-graph-evidence-workbench.jpg` | 1440×900 | 43 节点/72 边的 SVG 图谱与等价键盘表格 |
| `11-precise-element-citation.jpg` | 1440×900 | citation 跳转到高亮 heading 元素与相邻证据 |
| `12-mobile-multimodal-expert.jpg` | 390×844 | 图片入口、专家参数和无横向溢出的移动布局 |
| `13-evidence-ledger-login.png` | 1440×900 | Production Local 不对称登录页、实例定位与会话安全边界 |
| `14-evidence-ledger-mobile.png` | 390×844 | 极简问答首页、紧凑命令栏、底部导航与无横向溢出 |
| `15-question-first-debug.png` | 1440×900 | 调试模式按需展开 BM25、向量、Graph、MMR 与 rerank 参数 |
| `16-question-first-sources.png` | 1440×900 | FastAPI 反向代理问题的仅检索结果、匹配状态与五条相关来源 |

## 更新截图

1. 使用离线 provider 启动 Docker Compose。
2. 运行 `npm run demo:bootstrap`。
3. 只使用仓库脱敏问题和样例资料。
4. 分别覆盖简洁模式、调试 Trace、拒答、390px 与错误恢复。
5. 截图前检查页面没有 API Key、私有 URL、真实路径或系统通知。
6. 更新本清单和 README alt text。

README 直接展示的当前工作台截图（`01`、`13`、`14`、`15`）由离线 Playwright fixture 可重复生成：

```bash
CAPTURE_README_SCREENSHOTS=1 npm --prefix frontend run test:e2e -- workbench.spec.ts
```

生成过程只请求本地 Vite 与测试内 mock API，不会连接真实 Provider、生产数据库或用户资料。`16-question-first-sources.png` 展示的是受控样例资料的原始技术片段；其中的英文代码、产品名和协议名按证据原文保留，不作伪造翻译。

截图是人工证据，不能替代 Playwright。界面行为变化时必须先更新自动化测试，再更新截图。
