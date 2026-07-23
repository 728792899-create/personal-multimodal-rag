# 检索与可信回答

这份文档解释系统如何把“找得到”“看懂多模态内容”和“答得有依据”分开处理。默认 hash embedding 与 template enrichment 只为离线可复现服务，下面描述的是工程链路，不是对默认语义或视觉质量的夸大。

![十阶段多模态与 Graph 检索管线](assets/retrieval-pipeline.svg)

## 为什么保留混合检索

| 问题形态 | BM25 更有优势 | 向量检索更有优势 |
| --- | --- | --- |
| 产品名、错误码、配置项 | 精确词项匹配 | 可能因词面差异丢失 |
| 同义改写、自然语言描述 | 词项不重合时较弱 | 语义相似更稳定 |
| 罕见专有名词 | 通常可靠 | 依赖 embedding 模型 |
| 概念性问题 | 依赖资料措辞 | 更容易覆盖相关段落 |

Graph-lite 不替代这两个分支。它只在存在带来源的实体关系时导航到证据 chunk，再通过加权 RRF 汇入候选池；没有 evidence element 的边不能单独支撑答案或引用。

## 十个阶段

### 1. Query enrichment

纯文本问题保持原事件顺序。附加图片时，系统先验证真实图片签名、像素、动画和知识库边界，再用 OCR、尺寸/格式元数据及可选视觉 provider 产生受限查询扩展。原始问题仍用于生成，扩展文本只帮助检索；Trace 记录附件、detail、provider 和 fallback。

### 2. BM25 召回

把 query 分词后，与 chunk 词项频率和逆文档频率比较。它对文件名、技术名词、环境变量和错误文本特别有效。Trace 记录候选数量、`bm25_score` 与匹配词。

### 3. 向量召回

通过 embedding adapter 生成 query vector，再从 memory、Chroma 或 pgvector adapter 召回相似 chunk。默认 `mock` 是 deterministic hash embedding，零 Key且跨运行可复现，但不能代表生产语义模型。

### 4. 融合与去重

Hybrid 模式保留各分支原始分数并按权重归一融合。相同 chunk 只保留一次。融合分数用于相对排序，不应解释为概率。

### 5. Graph 导航

`hybrid_graph` 用问题中的实体 seed 查询同一知识库内、带 `evidence_element_id` 的关系边；`auto` 只有在关系/多跳意图和有效边同时成立时才启用。Graph 结果按 `k=60` 的 weighted RRF 融入候选，默认 graph weight 为 `0.25`。SVG 路径视图始终配有可键盘操作的等价表格。

### 6. Parent context expansion

元素命中后可补入同一父元素及相邻上下文，避免表格单元、图片 caption 或公式脱离标题路径。chunk 保留 `element_ids`、modality 和父级定位，引用可以回到文档查看器中的精确元素。

### 7. MMR 多样化

Maximum Marginal Relevance 在相关性与结果差异之间取舍：

```text
MMR = λ × relevance − (1 − λ) × max_similarity_to_selected
```

较高 `λ` 更重视原始相关性；较低 `λ` 更主动减少重复。调得过低可能牺牲最相关证据。

### 8. Rerank

默认 keyword reranker 保持离线可运行。可选模型通过 adapter 接入，并记录 provider、耗时和 fallback。Rerank 只能调整已有候选，不能补回初始召回完全遗漏的资料。

### 9. 回答或拒答

拒答门综合最低分、候选相关性和通用噪声，而不只判断候选数组是否为空。无候选、低于门槛、仅有泛词或检索失败且无可信 fallback 都会拒答。拒答是正确产品结果，响应仍携带 Trace、缺口分析和修复建议。

### 10. 引用审计

生成完成后才展示最终审计，检查引用来源、主张覆盖、grounding 置信度和无支撑主张。流式正文完成前标记为“待审计”，避免把半成品误认为可信答案。

## 策略与 profile

| 策略 | 启用链路 | 用途 |
| --- | --- | --- |
| `hybrid` | BM25 + Vector → Fusion → Parent/MMR/Rerank → Gate | 默认稳定路径 |
| `hybrid_graph` | Hybrid + Graph RRF → Parent/MMR/Rerank → Gate | 明确关系和多跳问题 |
| `auto` | 意图与 provenance 双门控后选择上述路径 | 普通模式默认 |

`keyword`、`semantic` 仍作为兼容检索模式保留。`balanced`、`precision`、`recall` profile 是参数意图，不是固定质量承诺；专家参数会覆盖 profile 默认值，评测必须记录完整参数。

## 如何阅读一条 Trace

1. **Query enrichment**：图片或改写是否偏离原意？
2. **Recall**：目标元素是否进入 BM25 或 vector 候选？
3. **Fusion**：正确 chunk 是否被权重或去重压低？
4. **Graph**：关系边是否有证据元素，路径是否跨错知识库？
5. **Parent context**：标题、表格、caption 和相邻元素是否完整？
6. **MMR / Rerank**：证据为何被移除或改变顺序？
7. **Decision**：门槛和理由码是否符合产品预期？
8. **Citation**：最终主张能否回到原件、页码和元素？

## 常见故障定位

| 表现 | 首先检查 | 常见修复 |
| --- | --- | --- |
| 图片问题没有召回 | enrichment 事件、OCR/视觉 provider、KB 范围 | 重传有效图片、启用合适 provider、修复 OCR |
| 多跳问题退化为关键词 | Graph seed/path、edge provenance | 补充可验证关系、检查 graph build/index version |
| 明明有资料却拒答 | BM25/vector 候选、文档范围 | 补同义词、扩大 candidate K、换 embedding |
| 回答引用重复段落 | Parent expansion、MMR 与 overlap | 缩小 parent window、调整 λ 或切分策略 |
| 第一引用来自错误文档 | 分支分数、Graph 权重与 rerank | 调整权重、补负样本、升级 reranker |
| 回答流畅但引用不足 | citation audit | 提高覆盖门槛、约束生成或拒答 |

## 可量化指标

除 Recall@5、MRR、首条引用准确率、拒答准确率和回答接受率外，0.3 还固定检查 modality Recall@5、表格单元、caption、公式、Graph path precision、Graph evidence coverage 与多跳 Recall@5。定义、阈值和 100 条 case 构成见[测试与评测](testing-and-evaluation.md)。
