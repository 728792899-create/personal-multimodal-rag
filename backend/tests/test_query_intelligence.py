from app.services.query_intelligence import analyze_query


def test_connector_must_appear_before_a_question_mark_for_composite_route():
    assert analyze_query("请同时说明原因？")["route"] == "composite"
    assert analyze_query("先问？然后同时说明")["route"] == "semantic"


def test_redos_shaped_repeated_connector_input_is_safe():
    query = "分别" + ("以及" * 20_000)

    analysis = analyze_query(query)

    assert analysis["route"] == "composite"
    assert analysis["decision_factors"] == ["comparison_operator"]
