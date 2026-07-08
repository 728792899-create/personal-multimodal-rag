# 演示脚本

## 准备

```bash
npm install
cp .env.example .env
npm run dev
```

导入演示资料：

```bash
npm run demo:bootstrap
```

## 演示路径

1. 打开 `http://127.0.0.1:5173`。
2. 查看已导入的 `samples/demo-documents/` 文档。
3. 输入问题：`这个 RAG 系统的核心工程亮点是什么？`
4. 查看答案、引用片段、score 和 retrieval trace。
5. 切换搜索模式，对比 keyword、semantic 和 hybrid。
6. 输入问题：`这份资料有没有提到 Kubernetes 部署？`
7. 观察资料不足时的 fallback、diagnostics 和拒答提示。
8. 对不满意的答案提交负反馈，生成 eval draft。
9. 使用答案加工能力生成项目说明、要点列表、学习笔记或 FAQ。
10. 将有价值的答案保存为知识卡片。

## 验收点

- 无 API Key 也能完成上传、检索、回答和引用展示。
- 答案能看到引用来源和上下文。
- 检索 trace 能说明候选片段如何被筛选。
- 证据不足时有明确提示，不把缺失资料编造成事实。
- 反馈样本可以进入评测流程。
