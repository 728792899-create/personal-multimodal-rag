from pathlib import Path
from types import SimpleNamespace

from app.services.document_processor import DocumentProcessor
from app.services.rag_engine import (
    RagEngine,
    _extract_direct_identifiers,
    _extract_identifier_contexts,
)
from app.services.retriever import HybridRetriever


class StaticRetriever:
    def __init__(self, ranked: list[dict]):
        self.ranked = ranked

    def search(self, question: str, top_k: int = 5, **options):
        return self.ranked, {
            "available_chunks": len(self.ranked),
            "search_mode": options.get("search_mode", "hybrid"),
            "fallbacks": [],
        }


def _real_engine(tmp_path: Path) -> RagEngine:
    source = tmp_path / "rag.md"
    source.write_text("RAG 使用 BM25 向量检索和引用来降低幻觉。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))
    return RagEngine(retriever, grounding_min_confidence=0.15)


def test_no_ranked_evidence_is_refused():
    engine = RagEngine(StaticRetriever([]), no_answer_threshold=0.05, grounding_min_confidence=0.15)

    result = engine.ask("unknown question")

    assert result["citations"] == []
    assert result["generation_trace"]["skipped"] is True
    assert result["generation_trace"]["reason"] == "no_evidence"
    assert result["retrieval_trace"]["refuse_reason"] == "no_evidence"


def test_weak_score_without_matched_terms_is_refused():
    ranked = [
        {
            "score": 0.10,
            "rerank_score": 0.10,
            "matched_terms": [],
            "chunk": object(),
        }
    ]
    engine = RagEngine(
        StaticRetriever(ranked),
        no_answer_threshold=0.05,
        grounding_min_confidence=0.15,
    )

    result = engine.ask("question with no lexical support")

    assert result["citations"] == []
    assert result["generation_trace"]["reason"] == "weak_grounding"
    assert result["retrieval_trace"]["refuse_reason"] == "weak_grounding"


def test_off_topic_question_is_refused_with_real_retrieval(tmp_path):
    result = _real_engine(tmp_path).ask(
        "iOS 原生支付对账集群",
        search_mode="keyword",
        query_rewrite=False,
    )

    assert result["citations"] == []
    assert result["generation_trace"]["reason"] in {
        "no_evidence",
        "below_threshold",
        "weak_grounding",
    }


def test_on_topic_question_still_returns_evidence(tmp_path):
    result = _real_engine(tmp_path).ask(
        "BM25 向量检索",
        search_mode="keyword",
        query_rewrite=False,
    )

    assert result["citations"]


def test_mock_embedding_rejects_only_generic_lexical_overlap(tmp_path):
    source = tmp_path / "workflow.md"
    source.write_text("系统提供检索流程、参数配置和 API 封装。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))

    result = RagEngine(retriever).ask("视频转码 HLS 切片参数怎么配置？", query_rewrite=False)

    assert result["citations"] == []
    assert result["retrieval_trace"]["refusal_reason"] == "weak_grounding"


def test_mock_embedding_rejects_project_only_overlap(tmp_path):
    source = tmp_path / "overview.md"
    source.write_text("该项目面向个人知识库问答，目标是展示检索链路。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))

    result = RagEngine(retriever).ask(
        "本项目的支付对账 SLA 和退款审批规则是什么？",
        query_rewrite=False,
    )

    assert result["citations"] == []
    assert result["retrieval_trace"]["refusal_reason"] == "weak_grounding"


def test_mock_embedding_rejects_automatic_only_overlap(tmp_path):
    source = tmp_path / "jobs.md"
    source.write_text("索引任务最多自动尝试三次，失败后记录脱敏错误。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))

    result = RagEngine(retriever).ask(
        "支付系统的每日对账差异如何自动冲正？",
        min_score=0.05,
        query_rewrite=False,
    )

    assert result["citations"] == []
    assert result["retrieval_trace"]["refusal_reason"] == "weak_grounding"


def test_deterministic_idempotency_alias_finds_explicit_evidence(tmp_path):
    source = tmp_path / "jobs.md"
    source.write_text("内容哈希和索引版本共同组成幂等键。", encoding="utf-8")
    processor = DocumentProcessor()
    document = processor.parse_file(source)
    retriever = HybridRetriever()
    retriever.add_document(document, processor.split(document))

    result = RagEngine(retriever).ask("重复提交是如何避免的？", query_rewrite=False)

    assert result["citations"]
    assert "幂等键" in result["citations"][0]["text"]


def test_direct_identifier_parser_preserves_version_identifiers():
    assert _extract_direct_identifiers(
        "A100、release-v2.1 与 module_name-3；123invalid 以及 no-digits"
    ) == ["a100", "release-v2.1", "module_name-3"]


def test_direct_identifier_parser_preserves_unicode_boundaries_and_trailing_underscore():
    assert _extract_direct_identifiers("解释模型v2、v3配置和 module3_") == ["module3_"]


def test_identifier_context_binds_entities_without_treating_question_words_as_entities():
    assert _extract_identifier_contexts("Aurora v2 的配置") == {("aurora", "v2")}
    assert _extract_identifier_contexts("Aurora version v2 settings") == {
        ("aurora", "v2")
    }
    assert _extract_identifier_contexts("Aurora 版本 v2 的配置") == {
        ("aurora", "v2")
    }
    assert _extract_identifier_contexts("What v2 features are supported?") == set()
    assert _extract_identifier_contexts("upgrade from v1 to v2") == set()
    assert _extract_identifier_contexts("比较极光v2和北辰v2") == {
        ("极光", "v2"),
        ("北辰", "v2"),
    }
    assert _extract_identifier_contexts("Aurora API v2 authentication") == {
        ("aurora api", "v2")
    }
    assert _extract_identifier_contexts("aurora api v2 authentication") == {
        ("aurora api", "v2")
    }
    assert _extract_identifier_contexts("Aurora (v2) timeout") == {
        ("aurora", "v2")
    }
    assert _extract_identifier_contexts("Aurora-Core v2 timeout") == {
        ("aurora core", "v2")
    }
    assert _extract_identifier_contexts("Use Aurora v2") == {("aurora", "v2")}
    assert _extract_identifier_contexts("New Aurora v2") == {("aurora", "v2")}
    assert _extract_identifier_contexts("请帮我查询极光v2") == {
        ("\u6781\u5149", "v2")
    }
    assert _extract_identifier_contexts("我想了解极光v2") == {
        ("\u6781\u5149", "v2")
    }
    assert _extract_identifier_contexts("Aurora Cloud API v2") == {
        ("aurora cloud api", "v2")
    }


def test_identifier_gate_handles_chinese_entities_and_never_joins_leaves():
    engine = RagEngine(StaticRetriever([]))
    wrong_chinese_entity = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["管理员口令", "v2"],
            "chunk": SimpleNamespace(text="北辰 v2 的管理员口令是 7788"),
        }
    ]
    cross_leaf_relation = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["aurora", "timeout"],
            "chunk": SimpleNamespace(text="Release notes for Aurora"),
        },
        {
            "score": 0.9,
            "rerank_score": 0.9,
            "matched_terms": ["v2", "timeout"],
            "chunk": SimpleNamespace(text="v2 belongs to Borealis and has a 60s timeout"),
        },
    ]

    assert engine._should_refuse(
        "极光 v2 的管理员口令？", wrong_chinese_entity, 0.95, 0.05
    ) == (True, "identifier_mismatch")
    assert engine._should_refuse(
        "Aurora v2 timeout?", cross_leaf_relation, 0.95, 0.05
    ) == (True, "identifier_mismatch")


def test_identifier_gate_requires_entity_version_and_target_in_one_leaf():
    engine = RagEngine(StaticRetriever([]))
    split_entity_and_target = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["aurora", "v2"],
            "chunk": SimpleNamespace(text="Aurora v2 release notes."),
        },
        {
            "score": 0.9,
            "rerank_score": 0.9,
            "matched_terms": ["v2", "timeout"],
            "chunk": SimpleNamespace(
                text="Borealis v2 timeout is 60 seconds."
            ),
        },
    ]

    assert engine._should_refuse(
        "What is Aurora v2 timeout?",
        split_entity_and_target,
        0.95,
        0.05,
    ) == (True, "identifier_mismatch")


def test_identifier_gate_allows_comparison_evidence_across_leaves():
    engine = RagEngine(StaticRetriever([]))
    comparison_evidence = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["aurora", "v2", "timeout"],
            "chunk": SimpleNamespace(text="Aurora v2 timeout is 60 seconds."),
        },
        {
            "score": 0.9,
            "rerank_score": 0.9,
            "matched_terms": ["borealis", "v2", "timeout"],
            "chunk": SimpleNamespace(text="Borealis v2 timeout is 45 seconds."),
        },
    ]

    assert engine._should_refuse(
        "Compare Aurora v2 and Borealis v2 timeout.",
        comparison_evidence,
        0.95,
        0.05,
    ) == (False, "")


def test_identifier_gate_requires_target_evidence_for_each_comparison_side():
    engine = RagEngine(StaticRetriever([]))
    missing_borealis_target = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["aurora", "v2", "timeout"],
            "chunk": SimpleNamespace(text="Aurora v2 timeout is 60 seconds."),
        },
        {
            "score": 0.9,
            "rerank_score": 0.9,
            "matched_terms": ["borealis", "v2"],
            "chunk": SimpleNamespace(text="Borealis v2 release notes."),
        },
    ]
    third_party_target = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["aurora", "v2"],
            "chunk": SimpleNamespace(text="Aurora v2 release notes."),
        },
        {
            "score": 0.9,
            "rerank_score": 0.9,
            "matched_terms": ["borealis", "v2"],
            "chunk": SimpleNamespace(text="Borealis v2 release notes."),
        },
        {
            "score": 0.85,
            "rerank_score": 0.85,
            "matched_terms": ["celeste", "v2", "timeout"],
            "chunk": SimpleNamespace(text="Celeste v2 timeout is 30 seconds."),
        },
    ]

    assert engine._should_refuse(
        "Compare Aurora v2 and Borealis v2 timeout.",
        missing_borealis_target,
        0.95,
        0.05,
    ) == (True, "identifier_mismatch")
    assert engine._should_refuse(
        "Compare Aurora v2 and Borealis v2 timeout.",
        third_party_target,
        0.95,
        0.05,
    ) == (True, "identifier_mismatch")


def test_identifier_gate_accepts_equivalent_supported_entity_spellings():
    engine = RagEngine(StaticRetriever([]))
    ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["aurora", "core", "v2"],
            "chunk": SimpleNamespace(text="Aurora-Core v2 timeout is 60s"),
        }
    ]

    assert engine._should_refuse(
        "Aurora Core (v2) timeout?", ranked, 0.95, 0.05
    ) == (False, "")


def test_identifier_gate_normalizes_bound_and_spaced_version_spellings():
    engine = RagEngine(StaticRetriever([]))
    bound = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["aurora", "v2", "timeout"],
            "chunk": SimpleNamespace(text="Aurora-v2 timeout is 60 seconds"),
        }
    ]
    spaced = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["aurora", "v2", "timeout"],
            "chunk": SimpleNamespace(text="Aurora v2 timeout is 60 seconds"),
        }
    ]

    assert _extract_identifier_contexts("Aurora-v2 timeout") == {
        ("aurora", "v2")
    }
    assert engine._should_refuse(
        "Aurora v2 timeout?", bound, 0.95, 0.05
    ) == (False, "")
    assert engine._should_refuse(
        "Aurora-v2 timeout?", spaced, 0.95, 0.05
    ) == (False, "")


def test_identifier_gate_ignores_caption_wrapper_around_error_code():
    engine = RagEngine(StaticRetriever([]))
    ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["img", "11", "504", "错误"],
            "chunk": SimpleNamespace(
                text=(
                    "## IMG-11 错误恢复 Caption IMG-11：504 错误卡显示 "
                    "request ID、重试按钮和已保留的问题文本。"
                )
            ),
        }
    ]

    assert _extract_identifier_contexts("Caption IMG-11：504 错误卡") >= {
        ("img", "11"),
        ("img 11", "504"),
    }
    assert _extract_identifier_contexts("Caption v2 rendering") == {
        ("caption", "v2")
    }
    assert engine._should_refuse(
        "IMG-11 的 504 错误卡保留哪些恢复信息？", ranked, 0.95, 0.05
    ) == (False, "")


def test_identifier_gate_rejects_wrong_numeric_versions_and_models():
    engine = RagEngine(StaticRetriever([]))
    wrong_version = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["aurora", "timeout"],
            "chunk": SimpleNamespace(text="Aurora 3.0 timeout is 60 seconds"),
        }
    ]
    wrong_model = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["iphone", "camera"],
            "chunk": SimpleNamespace(text="iPhone 14 camera has 12MP"),
        }
    ]
    wrong_entity = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["timeout", "2.0"],
            "chunk": SimpleNamespace(text="Borealis 2.0 timeout is 60 seconds"),
        }
    ]
    exact_model = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["iphone", "15", "camera"],
            "chunk": SimpleNamespace(text="iPhone 15 camera has 48MP"),
        }
    ]

    assert _extract_identifier_contexts("Aurora 2.0 timeout") == {
        ("aurora", "2.0")
    }
    assert _extract_identifier_contexts("iPhone 15 camera") == {
        ("iphone", "15")
    }
    assert _extract_identifier_contexts("timeout 60 seconds") == set()
    assert engine._should_refuse(
        "Aurora 2.0 timeout?", wrong_version, 0.95, 0.05
    ) == (True, "identifier_mismatch")
    assert engine._should_refuse(
        "iPhone 15 camera?", wrong_model, 0.95, 0.05
    ) == (True, "identifier_mismatch")
    assert engine._should_refuse(
        "Aurora 2.0 timeout?", wrong_entity, 0.95, 0.05
    ) == (True, "identifier_mismatch")
    assert engine._should_refuse(
        "iPhone 15 camera?", exact_model, 0.95, 0.05
    ) == (False, "")


def test_identifier_gate_does_not_depend_on_product_case_and_handles_numeric_labels():
    engine = RagEngine(StaticRetriever([]))
    wrong_lowercase_model = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["iphone", "camera"],
            "chunk": SimpleNamespace(text="iphone 14 camera has 12MP"),
        }
    ]
    wrong_version_label = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["model", "release"],
            "chunk": SimpleNamespace(text="Model 2024-09 release notes"),
        }
    ]
    equivalent_bound_label = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["model", "release"],
            "chunk": SimpleNamespace(text="Model-2024-08 release notes"),
        }
    ]

    assert _extract_identifier_contexts("iphone 15 camera") == {
        ("iphone", "15")
    }
    assert _extract_identifier_contexts("Model-2024-08 release notes") == {
        ("model", "2024-08")
    }
    assert engine._should_refuse(
        "iphone 15 camera?", wrong_lowercase_model, 0.95, 0.05
    ) == (True, "identifier_mismatch")
    assert engine._should_refuse(
        "Model 2024-08 release notes?", wrong_version_label, 0.95, 0.05
    ) == (True, "identifier_mismatch")
    assert engine._should_refuse(
        "Model 2024-08 release notes?", equivalent_bound_label, 0.95, 0.05
    ) == (False, "")
    assert engine._should_refuse(
        "版本 2024-08 的发布日期？", wrong_version_label, 0.95, 0.05
    ) == (True, "identifier_mismatch")


def test_identifier_context_ignores_natural_question_prefixes():
    assert _extract_identifier_contexts("Tell me about Aurora Cloud API v2") == {
        ("aurora cloud api", "v2")
    }
    assert _extract_identifier_contexts("能否介绍一下极光v2") == {
        ("极光", "v2")
    }


def test_similar_identifier_cannot_bypass_explicit_evidence_gap():
    ranked = [
        {
            "score": 0.9,
            "rerank_score": 0.9,
            "matched_terms": ["配置"],
            "chunk": SimpleNamespace(text="模型 v20 的配置未提供"),
        }
    ]
    engine = RagEngine(StaticRetriever(ranked))

    assert engine._should_refuse("解释 v2 的缺失配置", ranked, 0.9, 0.05) == (
        True,
        "explicit_evidence_gap",
    )


def test_availability_question_can_report_an_exact_documented_gap():
    ranked = [
        {
            "score": 0.9,
            "rerank_score": 0.9,
            "matched_terms": ["nova", "v2", "密钥"],
            "chunk": SimpleNamespace(text="Nova v2 的加密密钥未提供"),
        }
    ]
    engine = RagEngine(StaticRetriever(ranked))

    assert engine._should_refuse(
        "Nova v2 是否提供加密密钥？", ranked, 0.9, 0.05
    ) == (False, "")
    assert engine._should_refuse(
        "Nova v2 有提供加密密钥吗？", ranked, 0.9, 0.05
    ) == (False, "")
    assert engine._should_refuse(
        "Does Nova v2 provide an encryption key?", ranked, 0.9, 0.05
    ) == (False, "")


def test_yes_no_fact_question_does_not_bypass_a_documented_gap():
    ranked = [
        {
            "score": 0.9,
            "rerank_score": 0.9,
            "matched_terms": ["nova", "v2", "默认超时"],
            "chunk": SimpleNamespace(text="Nova v2 的默认超时未提供"),
        }
    ]
    engine = RagEngine(StaticRetriever(ranked))

    assert engine._should_refuse(
        "Nova v2 是否默认超时为 60 秒？", ranked, 0.9, 0.05
    ) == (True, "explicit_evidence_gap")


def test_unrelated_gap_marker_does_not_reject_supported_target_field():
    engine = RagEngine(StaticRetriever([]))
    ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2", "默认超时"],
            "chunk": SimpleNamespace(
                text="Nova v2 的默认超时为 60 秒；管理员口令未提供。"
            ),
        }
    ]
    split_ranked = [
        {
            "score": 0.96,
            "rerank_score": 0.96,
            "matched_terms": ["nova", "v2", "默认超时"],
            "chunk": SimpleNamespace(text="Nova v2 的默认超时为 60 秒"),
        },
        {
            "score": 0.94,
            "rerank_score": 0.94,
            "matched_terms": ["nova", "v2", "管理员口令"],
            "chunk": SimpleNamespace(text="Nova v2 的管理员口令未提供"),
        },
    ]

    assert engine._should_refuse(
        "Nova v2 的默认超时是多少？", ranked, 0.95, 0.05
    ) == (False, "")
    assert engine._should_refuse(
        "Nova v2 的默认超时是多少？", split_ranked, 0.96, 0.05
    ) == (False, "")

    english_ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2", "timeout"],
            "chunk": SimpleNamespace(
                text="Nova v2 timeout is 60 seconds. Password not available."
            ),
        }
    ]
    assert engine._should_refuse(
        "What is Nova v2 timeout?", english_ranked, 0.95, 0.05
    ) == (False, "")


def test_lower_rank_same_identifier_gap_requires_requested_field_match():
    engine = RagEngine(StaticRetriever([]))
    ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2"],
            "chunk": SimpleNamespace(
                text="Nova v2 default timeout is 60 seconds."
            ),
        },
        {
            "score": 0.8,
            "rerank_score": 0.8,
            "matched_terms": ["nova", "v2"],
            "chunk": SimpleNamespace(
                text="Nova v2 administrator password is not provided."
            ),
        },
    ]

    assert engine._should_refuse(
        "Nova v2 的默认超时是多少？", ranked, 0.95, 0.05
    ) == (False, "")


def test_top_rank_pure_gap_fails_closed_without_lexical_overlap():
    engine = RagEngine(StaticRetriever([]))
    ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": [],
            "chunk": SimpleNamespace(
                text="The administrator password is not provided."
            ),
        }
    ]

    assert engine._should_refuse(
        "管理员口令是什么？", ranked, 0.95, 0.05
    ) == (True, "explicit_evidence_gap")


def test_top_rank_wrapper_sentence_cannot_hide_cross_language_gap():
    engine = RagEngine(StaticRetriever([]))
    ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": [],
            "chunk": SimpleNamespace(
                text=(
                    "Password policy.\n"
                    "The administrator password is not provided."
                )
            ),
        }
    ]

    assert engine._should_refuse(
        "管理员口令是什么？", ranked, 0.95, 0.05
    ) == (True, "explicit_evidence_gap")


def test_top_rank_identifier_gap_does_not_override_positive_same_leaf():
    engine = RagEngine(StaticRetriever([]))
    ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2"],
            "chunk": SimpleNamespace(
                text=(
                    "Nova v2 default timeout is 60 seconds. "
                    "Nova v2 administrator password is not provided."
                )
            ),
        }
    ]

    assert engine._should_refuse(
        "What is Nova v2 default timeout?", ranked, 0.95, 0.05
    ) == (False, "")


def test_top_rank_identifier_can_link_cross_language_gap_without_field_terms():
    engine = RagEngine(StaticRetriever([]))
    ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2"],
            "chunk": SimpleNamespace(
                text=(
                    "Nova v2 release notes. "
                    "Nova v2 administrator password is not provided."
                )
            ),
        }
    ]

    assert engine._should_refuse(
        "Nova v2 的管理员口令是什么？", ranked, 0.95, 0.05
    ) == (True, "explicit_evidence_gap")


def test_unmatched_generic_gap_leaf_does_not_override_exact_evidence():
    engine = RagEngine(StaticRetriever([]))
    ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["graphalpha3", "graphtarget3"],
            "chunk": SimpleNamespace(
                text=(
                    "GraphAlpha3 contains GraphBridge3. "
                    "GraphBridge3 uses GraphTarget3."
                )
            ),
        },
        {
            "score": 0.2,
            "rerank_score": 0.2,
            "matched_terms": [],
            "chunk": SimpleNamespace(
                text="当前资料没有提供 Kubernetes 生产监控配置。"
            ),
        },
    ]

    assert engine._should_refuse(
        "GraphAlpha3 与 GraphTarget3 的关系路径是什么？", ranked, 0.95, 0.05
    ) == (False, "")


def test_prefix_collision_in_gap_field_does_not_override_exact_evidence():
    engine = RagEngine(StaticRetriever([]))
    ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["img", "02", "querystar", "靠近", "相似度"],
            "chunk": SimpleNamespace(
                text=(
                    "Caption IMG-02：QueryStar 靠近 EvidenceMoon，"
                    "余弦相似度为 0.91。"
                )
            ),
        },
        {
            "score": 0.4,
            "rerank_score": 0.4,
            "matched_terms": ["对象"],
            "chunk": SimpleNamespace(
                text="当前演示资料没有提供对象存储或生产监控配置。"
            ),
        },
    ]

    assert engine._should_refuse(
        "IMG-02 中 QueryStar 靠近哪个对象，相似度多少？",
        ranked,
        0.95,
        0.05,
    ) == (False, "")


def test_unrelated_gap_sentence_in_same_leaf_does_not_override_target_fact():
    engine = RagEngine(StaticRetriever([]))
    ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["conflict", "01", "查询", "图片", "保留"],
            "chunk": SimpleNamespace(
                text=(
                    "CONFLICT-01：当前 v0.3 规则优先，查询图片保留 24 小时。"
                    "对于知识库未覆盖的外部专业操作问题，系统必须拒答。"
                )
            ),
        }
    ]

    assert engine._should_refuse(
        "CONFLICT-01 中查询图片当前保留多久？", ranked, 0.95, 0.05
    ) == (False, "")


def test_gap_matching_uses_exact_tokens_and_complete_target_coverage():
    engine = RagEngine(StaticRetriever([]))
    shared_default = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2", "default", "timeout"],
            "chunk": SimpleNamespace(
                text=(
                    "Nova v2 default timeout is 60 seconds. "
                    "Default retries not provided."
                )
            ),
        }
    ]
    substring_collision = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2", "port"],
            "chunk": SimpleNamespace(
                text="Nova v2 port is 443. Support contract not provided."
            ),
        }
    ]
    target_head_gap = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2", "default", "timeout"],
            "chunk": SimpleNamespace(
                text=(
                    "Nova v2 default timeout behavior is configurable. "
                    "Timeout value not provided."
                )
            ),
        }
    ]

    assert engine._should_refuse(
        "What is Nova v2 default timeout?", shared_default, 0.95, 0.05
    ) == (False, "")
    assert engine._should_refuse(
        "What is Nova v2 port?", substring_collision, 0.95, 0.05
    ) == (False, "")
    assert engine._should_refuse(
        "What is Nova v2 default timeout?", target_head_gap, 0.95, 0.05
    ) == (True, "explicit_evidence_gap")


def test_gap_matching_links_anaphoric_clauses_without_rejecting_other_fields():
    engine = RagEngine(StaticRetriever([]))
    english_anaphora = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2", "password"],
            "chunk": SimpleNamespace(
                text="For the Nova v2 password, it is not provided."
            ),
        }
    ]
    chinese_anaphora = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2", "加密密钥"],
            "chunk": SimpleNamespace(text="Nova v2 的加密密钥，资料未提供。"),
        }
    ]
    english_other_field = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2", "default", "timeout"],
            "chunk": SimpleNamespace(
                text=(
                    "Nova v2 default timeout is 60 seconds. "
                    "Connection timeout not provided."
                )
            ),
        }
    ]
    chinese_other_field = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2", "默认超时"],
            "chunk": SimpleNamespace(
                text="Nova v2 的默认超时为60秒；连接超时未提供。"
            ),
        }
    ]

    assert engine._should_refuse(
        "What is the Nova v2 password?", english_anaphora, 0.95, 0.05
    ) == (True, "explicit_evidence_gap")
    assert engine._should_refuse(
        "Nova v2 的加密密钥是什么？", chinese_anaphora, 0.95, 0.05
    ) == (True, "explicit_evidence_gap")
    assert engine._should_refuse(
        "What is Nova v2 default timeout?", english_other_field, 0.95, 0.05
    ) == (False, "")
    assert engine._should_refuse(
        "Nova v2 的默认超时是多少？", chinese_other_field, 0.95, 0.05
    ) == (False, "")


def test_conversation_enrichment_cannot_change_current_question_availability_intent():
    engine = RagEngine(StaticRetriever([]))
    ranked = [
        {
            "score": 0.95,
            "rerank_score": 0.95,
            "matched_terms": ["nova", "v2", "加密密钥"],
            "chunk": SimpleNamespace(text="Nova v2 的加密密钥未提供"),
        }
    ]

    assert engine._should_refuse(
        "它的加密密钥是什么？",
        ranked,
        0.95,
        0.05,
        reference_query="Nova v2 是否提供加密密钥？\n它的加密密钥是什么？",
    ) == (True, "explicit_evidence_gap")


def test_direct_identifier_parser_handles_adversarial_long_input_linearly():
    query = ("segment-without-digits-" * 20_000) + "tail"

    assert _extract_direct_identifiers(query) == []
