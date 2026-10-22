import io
import json
import threading

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app import discovery_ai as ai

PAPER = {
    "arxiv_id": "2406.11944",
    "arxiv_version": 1,
    "title": "Research on autonomous active perception",
    "abstract": "An abstract on robot perception.",
    "categories": ["cs.CV"],
}
INTERESTS = [
    {
        "id": "active",
        "name": "Active perception",
        "description": "机器人视觉感知",
        "keywords": ["active perception"],
        "exclude_keywords": [],
        "priority": 3,
    }
]
RESULT = {
    "decision": "recommend",
    "score": 85,
    "matched_directions": ["active"],
    "reason": "与主动视觉感知问题相关，方法有借鉴价值。",
    "summary": "这篇论文研究机器人的主动视觉感知，结合观测选择与空间建图，为复杂环境中的自主探索提供方法参考。",
}


def content(basis="abstract"):
    return ai._content(
        PAPER["abstract"], basis, "https://arxiv.org/abs/2406.11944v1", 24000
    )


def completion(result=None, **overrides):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": json.dumps(result or RESULT)},
            }
        ],
        "usage": {"total_tokens": 123},
    } | overrides


def fake_provider(monkeypatch, handler):
    original = httpx.Client

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "Client", client)


def test_official_html_is_extracted_without_scripts_or_references(monkeypatch):
    text = "Introduction methods experiments conclusion. " * 40
    html = (
        f"<html><article class='ltx_document'><script>injected</script><p>{text}</p>"
        "<section class='ltx_bibliography'>References secret</section></article></html>"
    )

    def request(url, **kwargs):
        assert url == "https://arxiv.org/html/2406.11944v1"
        assert kwargs["limit"] == 15_000_000
        return html.encode(), "text/html; charset=utf-8", url

    monkeypatch.setattr(ai.arxiv, "request", request)
    result = ai.fetch_content(PAPER)
    assert result["basis"] == "full_text"
    assert "Introduction methods" in result["text"]
    assert "injected" not in result["text"] and "secret" not in result["text"]
    assert len(result["content_hash"]) == 64


def test_long_html_keeps_body_and_end_and_is_labeled_partial(monkeypatch):
    html = (
        "<article>"
        + "OPENING " * 1000
        + "METHOD " * 1000
        + "CONCLUSION " * 1000
        + "</article>"
    )
    monkeypatch.setattr(
        ai.arxiv, "request", lambda url, **_: (html.encode(), "text/html", url)
    )
    result = ai.fetch_content(PAPER, max_chars=1000)
    assert result["basis"] == "partial_text"
    assert len(result["text"]) <= 1000
    assert (
        "OPENING" in result["text"]
        and "METHOD" in result["text"]
        and "CONCLUSION" in result["text"]
    )


def test_unavailable_html_and_pdf_fall_back_to_abstract(monkeypatch):
    urls = []

    def request(url, **kwargs):
        urls.append(url)
        if "/html/" in url:
            return b"<html><h1>HTML is not available</h1></html>", "text/html", url
        raise httpx.ConnectError("temporary network problem")

    monkeypatch.setattr(ai.arxiv, "request", request)
    result = ai.fetch_content(PAPER)
    assert result["basis"] == "abstract" and result["text"] == PAPER["abstract"]
    assert len(urls) == 2


@pytest.mark.parametrize(
    "identifier",
    ["https://evil.example/2406.11944", "../../etc/passwd", "2406.11944?x=1"],
)
def test_invalid_identifier_never_makes_a_request(monkeypatch, identifier):
    monkeypatch.setattr(
        ai.arxiv, "request", lambda *a, **kw: pytest.fail("unexpected request")
    )
    assert ai.fetch_content(PAPER | {"arxiv_id": identifier})["basis"] == "abstract"


def test_full_text_can_be_disabled(monkeypatch):
    monkeypatch.setattr(
        ai.arxiv, "request", lambda *a, **kw: pytest.fail("unexpected request")
    )
    assert ai.fetch_content(PAPER, try_full_text=False)["basis"] == "abstract"


def test_stop_after_html_failure_prevents_pdf_request(monkeypatch):
    stop = threading.Event()
    requests = []

    def request(url, **kwargs):
        requests.append(url)
        stop.set()
        raise ValueError("no HTML")

    monkeypatch.setattr(ai.arxiv, "request", request)
    with pytest.raises(ai.AIError) as caught:
        ai.fetch_content(PAPER, stop_event=stop)
    assert caught.value.code == "canceled"
    assert requests == ["https://arxiv.org/html/2406.11944v1"]


def test_wrong_paper_redirect_is_not_used(monkeypatch):
    monkeypatch.setattr(
        ai.arxiv,
        "request",
        lambda url, **kw: (
            b"<article>" + b"wrong paper " * 100 + b"</article>",
            "text/html",
            "https://arxiv.org/html/9999.99999",
        ),
    )
    assert ai.fetch_content(PAPER)["basis"] == "abstract"


def text_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 10 Tf 20 700 Td ("
        + b"Active perception and robot navigation. " * 50
        + b") Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_fallback_runs_real_isolated_extraction(monkeypatch):
    def request(url, **kwargs):
        if "/html/" in url:
            raise ValueError("not available")
        kwargs["destination"].write(text_pdf())
        return b"", "application/pdf", url

    monkeypatch.setattr(ai.arxiv, "request", request)
    result = ai.fetch_content(PAPER)
    assert result["basis"] == "full_text"
    assert "robot navigation" in result["text"]
    assert result["source_url"] == "https://arxiv.org/pdf/2406.11944v1"


def test_analyze_sends_json_without_secret_in_prompt_and_preserves_basis(monkeypatch):
    def handler(request):
        assert str(request.url) == ai.DEEPSEEK_URL
        assert request.headers["Authorization"] == "Bearer test-only-key"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert body["thinking"] == {"type": "disabled"}
        assert body["model"] == "deepseek-flash" and body["max_tokens"] == 800
        assert "test-only-key" not in json.dumps(body)
        data = json.loads(body["messages"][1]["content"])
        assert data["interest_description"] == "关注长期身份保持"
        return httpx.Response(200, json=completion())

    fake_provider(monkeypatch, handler)
    result = ai.analyze(
        PAPER,
        INTERESTS,
        content("partial_text"),
        api_key="test-only-key",
        interest_description="关注长期身份保持",
    )
    assert result["score"] == 85 and result["matched_directions"] == ["active"]
    assert result["basis"] == "partial_text" and result["tokens_used"] == 123


def test_natural_language_interest_can_recommend_without_direction_ids(monkeypatch):
    fake_provider(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=completion(RESULT | {"matched_directions": []})
        ),
    )
    result = ai.analyze(
        PAPER,
        [],
        content(),
        api_key="test-only-key",
        interest_description="无人机主动感知",
    )
    assert result["decision"] == "recommend" and result["matched_directions"] == []


@pytest.mark.parametrize(
    "interests,description", [([], "   "), (INTERESTS, "无人机主动感知")]
)
def test_empty_direction_matches_require_natural_language_only_configuration(
    monkeypatch, interests, description
):
    fake_provider(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=completion(RESULT | {"matched_directions": []})
        ),
    )
    with pytest.raises(ai.AIError) as caught:
        ai.analyze(
            PAPER,
            interests,
            content(),
            api_key="test-only-key",
            interest_description=description,
        )
    assert caught.value.code == "invalid_response"


def test_natural_language_only_rejects_invented_direction_ids(monkeypatch):
    fake_provider(monkeypatch, lambda request: httpx.Response(200, json=completion()))
    with pytest.raises(ai.AIError) as caught:
        ai.analyze(
            PAPER,
            [],
            content(),
            api_key="test-only-key",
            interest_description="无人机主动感知",
        )
    assert caught.value.code == "invalid_response"


@pytest.mark.parametrize(
    "change",
    [
        {"score": "90"},
        {"score": True},
        {"score": 101},
        {"decision": "maybe"},
        {"matched_directions": ["invented"]},
        {"matched_directions": []},
        {"matched_directions": ["active", "active"]},
        {"summary": "  "},
        {"unexpected": "field"},
    ],
)
def test_invalid_model_outputs_are_rejected_with_usage(monkeypatch, change):
    fake_provider(
        monkeypatch,
        lambda request: httpx.Response(200, json=completion(RESULT | change)),
    )
    with pytest.raises(ai.AIError) as caught:
        ai.analyze(PAPER, INTERESTS, content(), api_key="test-only-key")
    assert caught.value.code == "invalid_response" and caught.value.tokens_used == 123


@pytest.mark.parametrize("value", ["", "{bad json}", "[]", "```json\n{}\n```"])
def test_malformed_or_empty_model_json_is_rejected(monkeypatch, value):
    response = completion(
        choices=[{"finish_reason": "stop", "message": {"content": value}}]
    )
    fake_provider(monkeypatch, lambda request: httpx.Response(200, json=response))
    with pytest.raises(ai.AIError, match="返回格式"):
        ai.analyze(PAPER, INTERESTS, content(), api_key="test-only-key")


def test_truncated_output_preserves_reported_usage(monkeypatch):
    response = completion(
        choices=[{"finish_reason": "length", "message": {"content": "{}"}}]
    )
    fake_provider(monkeypatch, lambda request: httpx.Response(200, json=response))
    with pytest.raises(ai.AIError) as caught:
        ai.analyze(PAPER, INTERESTS, content(), api_key="test-only-key")
    assert (
        caught.value.code == "incomplete_response" and caught.value.tokens_used == 123
    )


def test_missing_usage_is_rejected_so_budget_reservation_can_be_preserved(monkeypatch):
    fake_provider(
        monkeypatch, lambda request: httpx.Response(200, json=completion(usage={}))
    )
    with pytest.raises(ai.AIError) as caught:
        ai.analyze(PAPER, INTERESTS, content(), api_key="test-only-key")
    assert caught.value.code == "invalid_response" and caught.value.tokens_used == 0


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (429, "rate_limited", True),
        (401, "authentication", False),
        (402, "insufficient_balance", False),
        (500, "provider_error", True),
        (302, "provider_error", False),
    ],
)
def test_provider_error_is_sanitized_and_not_automatically_retried(
    monkeypatch, status, code, retryable
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            text="echo secret test-only-key",
            headers={"Location": "https://evil.example"},
        )

    fake_provider(monkeypatch, handler)
    with pytest.raises(ai.AIError) as caught:
        ai.analyze(PAPER, INTERESTS, content(), api_key="test-only-key")
    assert len(requests) == 1
    assert caught.value.code == code and caught.value.retryable is retryable
    assert "test-only-key" not in str(caught.value)


def test_timeout_is_sanitized(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("secret test-only-key")

    fake_provider(monkeypatch, handler)
    with pytest.raises(ai.AIError) as caught:
        ai.analyze(PAPER, INTERESTS, content(), api_key="test-only-key")
    assert caught.value.code == "timeout" and "test-only-key" not in str(caught.value)


def test_model_and_missing_key_are_checked_before_network(monkeypatch):
    monkeypatch.setattr(
        ai.httpx, "Client", lambda **kw: pytest.fail("unexpected request")
    )
    with pytest.raises(ai.AIError) as caught:
        ai.analyze(PAPER, INTERESTS, content(), api_key="")
    assert caught.value.code == "not_configured"
    with pytest.raises(ai.AIError) as caught:
        ai.analyze(PAPER, INTERESTS, content(), api_key="test", model="evil\nmodel")
    assert caught.value.code == "invalid_model"


@pytest.mark.parametrize("key", ["测试密钥", "test\x00key", "test\tkey", "test\nkey"])
def test_invalid_header_secret_is_rejected_before_network(monkeypatch, key):
    monkeypatch.setattr(
        ai.httpx, "Client", lambda **kw: pytest.fail("unexpected request")
    )
    with pytest.raises(ai.AIError) as caught:
        ai.analyze(PAPER, INTERESTS, content(), api_key=key)
    assert caught.value.code == "not_configured" and key not in str(caught.value)


@pytest.mark.parametrize("description", ["三维感知" * 100, '主动\\感知\n"无人机"'])
def test_budget_estimate_includes_multibyte_prompt_and_output_allowance(description):
    small = ai.estimate_tokens(PAPER, INTERESTS, content(), max_output_tokens=800)
    large = ai.estimate_tokens(
        PAPER,
        INTERESTS,
        content(),
        max_output_tokens=1000,
        interest_description=description,
    )
    encoded_description = (
        len(json.dumps(description, ensure_ascii=False).encode("utf-8")) - 2
    )
    assert large == small + 200 + encoded_description
