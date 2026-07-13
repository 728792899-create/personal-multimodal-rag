import httpx

from app.services.responses_client import ResponsesClient


def test_responses_client_defaults_to_official_v1_endpoint_and_extracts_output_text_only():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "output": [
                    {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "private chain"}]},
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "grounded answer", "annotations": []},
                            {"type": "refusal", "refusal": "not used"},
                        ],
                    },
                ]
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ResponsesClient(
        api_key="test-key",
        model="test-model",
        base_url="",
        http_client=http_client,
    )

    assert client.create_text("Use only supplied evidence") == "grounded answer"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["authorization"] == "Bearer test-key"
    assert '"model":"test-model"' in captured["payload"].replace(" ", "")


def test_responses_client_rejects_success_response_without_output_text():
    http_client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"output": []}))
    )
    client = ResponsesClient(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        http_client=http_client,
    )

    try:
        client.create_text("question")
    except ValueError as exc:
        assert "text output" in str(exc).lower()
    else:
        raise AssertionError("empty Responses payload must fail instead of returning an empty answer")
