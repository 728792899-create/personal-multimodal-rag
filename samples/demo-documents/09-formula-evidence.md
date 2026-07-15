# 公式提取固定证据

FORM-01 加权融合公式：RRF(d) = 0.75/(60+rank_hybrid) + 0.25/(60+rank_graph)。

FORM-02 混合得分公式：score = 0.62*BM25_norm + 0.38*vector_similarity。

FORM-03 MMR 公式：MMR = 0.78*relevance - 0.22*redundancy。

FORM-04 召回率公式：Recall@5 = relevant_retrieved/total_relevant。

FORM-05 平均倒数排名：MRR = mean(1/first_relevant_rank)。

FORM-06 引用覆盖：coverage = supported_sentences/claim_sentences。

FORM-07 余弦相似度：cosine = dot(q,d)/(norm(q)*norm(d))。

FORM-08 指数退避：delay_n = min(base*2^(n-1),max_delay) + jitter。
