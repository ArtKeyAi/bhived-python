from __future__ import annotations

from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from bhived import APIError, DuplicateLessonError, WriteOutcomeUnknownError
from bhived_testkit import QUERY_RESPONSE, TEST_KEY, TEST_URL, WRITE_RESPONSE, error, make_client, ok

TEXT = "**Context:** httpx 0.28, respx 0.21\n**Solution:** pin httpx<1\n**Verified:** test suite passes"
TITLE = "Pin httpx<1 while respx 0.21 lacks httpx 1.0 support"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_write_posts_lesson_with_idempotency_key() -> None:
    client, api, _ = make_client(ok(WRITE_RESPONSE))
    result = client.write_instruction(TEXT, TITLE, query_id="q-1", model="claude-sonnet-5-5")

    request = api.requests[0]
    assert str(request.url) == f"{TEST_URL}/v1/memories"
    assert request.headers["X-API-Key"] == TEST_KEY
    assert len(request.headers["Idempotency-Key"]) == 32
    assert api.body() == {
        "text": TEXT,
        "title": TITLE,
        "type": "instruction",
        "action": "new",
        "query_id": "q-1",
        "model": "claude-sonnet-5-5",
    }
    assert result.bhived_id == "new-1"
    assert result.action_performed == "created"
    assert result.lesson_type == "instruction"
    assert result.query_id_linked == "q-123"
    assert not result.replayed


@pytest.mark.parametrize(
    ("method", "lesson_type"),
    [("write_instruction", "instruction"), ("write_mistake", "mistake"), ("write_update", "update")],
)
def test_each_write_sets_its_type(method: str, lesson_type: str) -> None:
    client, api, _ = make_client(ok(WRITE_RESPONSE))
    getattr(client, method)(TEXT, TITLE, query_id=None)
    assert api.body()["type"] == lesson_type


def test_writes_link_to_the_last_query_by_default() -> None:
    client, api, _ = make_client(ok(QUERY_RESPONSE), ok(WRITE_RESPONSE), ok(WRITE_RESPONSE), ok(WRITE_RESPONSE))
    client.query("x")
    client.write_instruction(TEXT, TITLE)
    assert api.body()["query_id"] == "q-123"

    client.write_mistake(TEXT, TITLE, query_id=None)
    assert "query_id" not in api.body()

    client.write_update(TEXT, TITLE, query_id="q-other")
    assert api.body()["query_id"] == "q-other"


def test_no_query_yet_means_no_link() -> None:
    client, api, _ = make_client(ok(WRITE_RESPONSE))
    client.write_instruction(TEXT, TITLE)
    assert "query_id" not in api.body()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"text": " ", "title": TITLE}, "text"),
        ({"text": TEXT, "title": ""}, "title"),
        ({"text": TEXT, "title": "x" * 101}, "title"),
        ({"text": TEXT, "title": TITLE, "action": "replace"}, "action"),
    ],
)
def test_invalid_writes_fail_before_any_request(kwargs, message) -> None:
    client, api, _ = make_client()
    with pytest.raises(ValueError, match=message):
        client.write_instruction(**kwargs)
    assert api.requests == []


def test_replayed_header_is_reported() -> None:
    client, _, _ = make_client(ok(WRITE_RESPONSE, headers={"Idempotency-Replayed": "true"}))
    assert client.write_instruction(TEXT, TITLE).replayed


def test_transient_failure_is_retried_once_with_the_same_key() -> None:
    client, api, sleeps = make_client(httpx.ReadTimeout, ok(WRITE_RESPONSE))
    client.write_instruction(TEXT, TITLE)
    assert len(api.requests) == 2
    assert api.header("Idempotency-Key", 0) == api.header("Idempotency-Key", 1)
    assert sleeps == [0.5]


def test_second_transient_failure_means_outcome_unknown() -> None:
    client, api, _ = make_client(error(502, "bad gateway"), error(500, "boom"))
    with pytest.raises(WriteOutcomeUnknownError) as caught:
        client.write_instruction(TEXT, TITLE)
    assert caught.value.reason == "server_error"
    assert len(api.requests) == 2


def test_unknown_outcome_keeps_the_key_for_an_identical_retry() -> None:
    client, api, _ = make_client(httpx.ConnectError, httpx.ConnectError, ok(WRITE_RESPONSE), ok(WRITE_RESPONSE))
    with pytest.raises(WriteOutcomeUnknownError) as caught:
        client.write_instruction(TEXT, TITLE)
    assert caught.value.reason == "network"
    first_key = api.header("Idempotency-Key", 0)

    client.write_instruction(TEXT, TITLE)
    assert api.header("Idempotency-Key", 2) == first_key

    # Once a write has resolved, the next identical write is a new write.
    client.write_instruction(TEXT, TITLE)
    assert api.header("Idempotency-Key", 3) != first_key


def test_different_content_gets_a_different_key() -> None:
    client, api, _ = make_client(httpx.ConnectError, httpx.ConnectError, ok(WRITE_RESPONSE))
    with pytest.raises(WriteOutcomeUnknownError):
        client.write_instruction(TEXT, TITLE)
    client.write_instruction(TEXT + " (edited)", TITLE)
    assert api.header("Idempotency-Key", 2) != api.header("Idempotency-Key", 0)


def test_write_in_progress_is_polled_using_retry_after() -> None:
    in_progress = error(409, {"error": "write_in_progress"}, headers={"Retry-After": "3"})
    client, api, sleeps = make_client(in_progress, in_progress, ok(WRITE_RESPONSE, headers={"Idempotency-Replayed": "true"}))
    result = client.write_instruction(TEXT, TITLE)
    assert result.replayed
    assert sleeps == [3.0, 3.0]
    assert len({api.header("Idempotency-Key", i) for i in range(3)}) == 1


def test_retry_after_from_body_http_date_and_bounds() -> None:
    later = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=120), usegmt=True)
    client, _, sleeps = make_client(
        error(409, {"error": "write_in_progress", "retry_after_seconds": 2}),
        error(409, {"error": "write_in_progress"}, headers={"Retry-After": "0"}),
        error(409, {"error": "write_in_progress"}),
        error(409, {"error": "write_in_progress"}, headers={"Retry-After": later}),
        ok(WRITE_RESPONSE),
    )
    client.write_instruction(TEXT, TITLE)
    assert sleeps == [2.0, 0.25, 5.0, 30.0]


def test_write_still_in_progress_at_the_deadline_is_unknown() -> None:
    clock = FakeClock()
    in_progress = error(409, {"error": "write_in_progress"}, headers={"Retry-After": "30"})

    def slow_in_progress(request: httpx.Request) -> httpx.Response:
        clock.now += 40
        return in_progress

    client, api, sleeps = make_client(*[slow_in_progress] * 10)
    client._clock = clock
    with pytest.raises(WriteOutcomeUnknownError) as caught:
        client.write_instruction(TEXT, TITLE)
    assert caught.value.reason == "in_progress"
    assert len(api.requests) < 10


def test_duplicate_is_a_definitive_answer() -> None:
    duplicate = error(409, {"error": "duplicate_memory", "duplicate_of": "m-old", "jaccard_similarity": 0.91})
    client, api, sleeps = make_client(duplicate, ok(WRITE_RESPONSE))
    with pytest.raises(DuplicateLessonError) as caught:
        client.write_instruction(TEXT, TITLE)
    assert caught.value.duplicate_of == "m-old"
    assert caught.value.similarity == pytest.approx(0.91)
    assert sleeps == []

    # A definitive answer releases the key.
    first_key = api.header("Idempotency-Key", 0)
    client.write_instruction(TEXT, TITLE)
    assert api.header("Idempotency-Key", 1) != first_key


def test_idempotency_rejection_is_an_api_error() -> None:
    client, _, _ = make_client(error(422, {"error": "idempotency_key_reused"}))
    with pytest.raises(APIError) as caught:
        client.write_instruction(TEXT, TITLE)
    assert caught.value.code == "idempotency_key_reused"
