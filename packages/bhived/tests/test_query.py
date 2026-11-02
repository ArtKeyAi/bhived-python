from __future__ import annotations

import httpx
import pytest

from bhived import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BhivedClient,
    BhivedConfig,
    RateLimitError,
)
from bhived_testkit import QUERY_RESPONSE, TEST_KEY, TEST_URL, error, make_client, ok


def test_query_sends_v2_request_with_key_header() -> None:
    client, api, _ = make_client(ok(QUERY_RESPONSE))
    client.query("  respx breaks with httpx 1.0  ", context="Python 3.12", top_k=5, scope="global_only")

    request = api.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{TEST_URL}/v2/query"
    assert request.headers["X-API-Key"] == TEST_KEY
    assert request.headers["User-Agent"].startswith("bhived-python/")
    assert api.body() == {
        "query": "respx breaks with httpx 1.0",
        "context": "Python 3.12",
        "top_k": 5,
        "scope": "global_only",
        "include_episodes": True,
        "include_warnings": True,
        "include_disputed": True,
    }


def test_optional_fields_are_left_out() -> None:
    client, api, _ = make_client(ok(QUERY_RESPONSE))
    client.query("anything")
    assert "scope" not in api.body()
    assert "context" not in api.body()


def test_query_result_is_parsed_and_query_id_remembered() -> None:
    client, _, _ = make_client(ok(QUERY_RESPONSE))
    result = client.query("respx httpx")

    assert result.query_id == "q-123"
    assert client.last_query_id == "q-123"
    assert [lesson.id for lesson in result.recommendations] == ["m-1", "m-2", "m-skill"]
    assert [lesson.id for lesson in result.lessons] == ["m-1", "m-2"]
    assert result.capabilities[0].capability_name == "pytest-helper"
    assert result.warnings[0].title == "Do NOT patch httpx.Client.send"
    assert result.disputed[0].b_id == "m-9"
    assert result.failed_approaches[0].text == "Flaky on Windows."
    assert all(item.tier == "public" for item in result.recommendations)
    assert not result.has_team_results


def test_team_results_are_kept_apart() -> None:
    data = dict(QUERY_RESPONSE)
    data["team_recommendations"] = [{"id": "t-1", "title": "Our proxy", "text": "Use the team proxy.", "score": 0.9}]
    client, _, _ = make_client(ok(data))
    result = client.query("proxy")
    assert result.has_team_results
    assert result.recommendations[0].tier == "team"
    assert result.team_recommendations[0].id == "t-1"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"query": "   "}, "query"),
        ({"query": "x", "top_k": 0}, "top_k"),
        ({"query": "x", "top_k": 101}, "top_k"),
        ({"query": "x", "scope": "everyone"}, "scope"),
    ],
)
def test_invalid_arguments_fail_before_any_request(kwargs, message) -> None:
    client, api, _ = make_client()
    with pytest.raises(ValueError, match=message):
        client.query(**kwargs)
    assert api.requests == []


def test_missing_key_fails_before_any_request() -> None:
    api_calls: list[httpx.Request] = []
    client = BhivedClient(
        config=BhivedConfig(api_key=None, api_url=TEST_URL),
        http_client=httpx.Client(transport=httpx.MockTransport(lambda r: api_calls.append(r))),
    )
    with pytest.raises(AuthenticationError, match="npx bhived setup"):
        client.query("anything")
    assert api_calls == []


def test_models_warming_is_retried_with_backoff() -> None:
    warming = error(503, {"error": "models_warming"})
    client, api, sleeps = make_client(warming, warming, warming, ok(QUERY_RESPONSE))
    result = client.query("x")
    assert result.query_id == "q-123"
    assert sleeps == [1.0, 2.0, 4.0]
    assert len(api.requests) == 4


def test_models_warming_gives_up_after_the_budget() -> None:
    warming = error(503, {"error": "models_warming"})
    client, api, sleeps = make_client(*[warming] * 6)
    with pytest.raises(APIError) as caught:
        client.query("x")
    assert caught.value.status_code == 503
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 10.0]
    assert len(api.requests) == 6


def test_warming_budget_is_configurable() -> None:
    warming = error(503, {"error": "models_warming"})
    client, api, sleeps = make_client(warming, warming, warmup_retries=1)
    with pytest.raises(APIError):
        client.query("x")
    assert sleeps == [1.0]


def test_plain_5xx_is_retried_once() -> None:
    client, api, sleeps = make_client(error(502, "bad gateway"), error(500, "boom"))
    with pytest.raises(APIError) as caught:
        client.query("x")
    assert caught.value.status_code == 500
    assert sleeps == [0.5]


def test_network_error_is_retried_once_then_reported() -> None:
    client, api, sleeps = make_client(httpx.ConnectError, httpx.ConnectError)
    with pytest.raises(APIConnectionError, match="Cannot connect"):
        client.query("x")
    assert sleeps == [0.5]


def test_timeout_is_reported_as_timeout() -> None:
    client, _, _ = make_client(httpx.ReadTimeout, httpx.ReadTimeout)
    with pytest.raises(APITimeoutError, match="timed out"):
        client.query("x")


def test_client_errors_are_not_retried() -> None:
    client, api, sleeps = make_client(error(422, "bad request"))
    with pytest.raises(APIError) as caught:
        client.query("x")
    assert caught.value.status_code == 422
    assert sleeps == []


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_raises_authentication_error_without_the_key(status: int) -> None:
    client, _, sleeps = make_client(error(status, "Invalid or inactive API key"))
    with pytest.raises(AuthenticationError) as caught:
        client.query("x")
    assert TEST_KEY not in str(caught.value)
    assert sleeps == []


def test_rate_limit_is_not_retried() -> None:
    client, _, sleeps = make_client(httpx.Response(429, text="Rate limit exceeded", headers={"Retry-After": "30"}))
    with pytest.raises(RateLimitError) as caught:
        client.query("x")
    assert caught.value.retry_after == "30"
    assert sleeps == []


def test_lenient_parsing_of_sparse_results() -> None:
    client, _, _ = make_client(ok({"query_id": "q-9", "public_recommendations": [{"text": "only text"}, "junk"]}))
    result = client.query("x")
    lesson = result.recommendations[0]
    assert (lesson.id, lesson.title, lesson.type, lesson.status, lesson.score) == ("unknown", "", "note", "active", 0.0)
    assert len(result.recommendations) == 1
    assert result.warnings == ()
