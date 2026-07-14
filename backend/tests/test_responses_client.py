import httpx
import json

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
    assert '"store":false' in captured["payload"].replace(" ", "")


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


def test_responses_client_streams_only_typed_output_text_events():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read())
        body = "\n\n".join(
            [
                'event: response.created\ndata: {"type":"response.created"}',
                'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"grounded "}',
                'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"stream"}',
                'event: response.completed\ndata: {"type":"response.completed","response":{"status":"completed"}}',
            ]
        )
        return httpx.Response(200, text=body + "\n\n", headers={"content-type": "text/event-stream"})

    client = ResponsesClient(
        api_key="test-key",
        model="test-model",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert list(client.stream_text("evidence")) == ["grounded ", "stream"]
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["store"] is False
