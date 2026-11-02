from __future__ import annotations

from bhived import QueryResult, WriteResult
from bhived._format import approx_tokens
from bhived_testkit import QUERY_RESPONSE, WRITE_RESPONSE


def test_markdown_lists_every_section_and_the_query_id() -> None:
    text = QueryResult.from_api(QUERY_RESPONSE).to_markdown()
    assert "## Shared lessons (3 found)" in text
    assert "Pin httpx below 1.0 with respx 0.21" in text
    assert "### Warnings (known mistakes)" in text
    assert "### Disputed pairs" in text
    assert "### Failed approaches" in text
    assert "pytest-helper" in text and "bhived-mcp" in text
    assert "query_id: `q-123`" in text
    assert "team" not in text.split("---")[0].lower()


def test_markdown_shows_team_section_only_with_team_results() -> None:
    data = dict(QUERY_RESPONSE, team_recommendations=[{"id": "t-1", "title": "Team fix", "text": "x", "score": 1}])
    text = QueryResult.from_api(data).to_markdown()
    assert "## Your team's lessons (1 found)" in text
    assert "## Public shared lessons (3 found)" in text


def test_markdown_for_empty_result() -> None:
    text = QueryResult.from_api({"query_id": "q-0"}).to_markdown()
    assert "No shared lessons matched" in text


def test_context_block_has_lessons_and_warnings_but_no_capabilities() -> None:
    block = QueryResult.from_api(QUERY_RESPONSE).as_context()
    assert block.startswith("## Shared lessons (from bhived)")
    assert "What worked:\n1. Pin httpx below 1.0" in block
    assert "Known mistakes:\n- Do NOT patch httpx.Client.send" in block
    assert "pytest-helper" not in block
    assert "query_id" not in block


def test_context_block_mentions_query_id_when_asked() -> None:
    block = QueryResult.from_api(QUERY_RESPONSE).as_context(mention_write_tools=True)
    assert "query_id: q-123" in block


def test_context_block_respects_the_token_cap() -> None:
    long_text = " ".join(["word"] * 400)
    data = {
        "query_id": "q-1",
        "public_recommendations": [
            {"id": f"m-{i}", "title": f"Lesson {i}", "text": long_text, "score": 0.5} for i in range(10)
        ],
        "public_warnings": [{"id": "w-1", "title": "Careful", "text": long_text}],
    }
    result = QueryResult.from_api(data)
    assert approx_tokens(result.as_context(max_tokens=120)) <= 120
    for cap in (200, 300, 800):
        block = result.as_context(max_tokens=cap)
        assert approx_tokens(block) <= cap
        assert "What worked" in block
        assert "Known mistakes" in block  # one long lesson must not push out the warning


def test_context_block_can_skip_warnings_and_is_empty_without_lessons() -> None:
    result = QueryResult.from_api(QUERY_RESPONSE)
    assert "Known mistakes" not in result.as_context(include_warnings=False)
    assert QueryResult.from_api({"query_id": "q"}).as_context() == ""


def test_write_markdown_notes() -> None:
    result = WriteResult.from_api(WRITE_RESPONSE, lesson_type="instruction", requested_query_id="q-123")
    text = result.to_markdown()
    assert text.startswith("Lesson created.")
    assert "bhived_id: `new-1`" in text
    assert "linked_query: `q-123`" in text

    corroborated = WriteResult.from_api(
        dict(WRITE_RESPONSE, action_performed="corroborated", query_id_linked=None), lesson_type="mistake"
    )
    assert "no new lesson was created" in corroborated.to_markdown()
    assert "Pass the query_id" in corroborated.to_markdown()


def test_write_markdown_flags_a_supersede_that_did_not_apply() -> None:
    result = WriteResult.from_api(WRITE_RESPONSE, lesson_type="instruction", requested_supersedes_id="m-theirs")
    assert "NOT replaced" in result.to_markdown()
    assert "`m-theirs` is unchanged" in result.to_markdown()
