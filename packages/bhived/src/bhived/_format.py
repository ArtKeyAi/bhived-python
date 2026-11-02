"""Plain Markdown renderings of results, written for an LLM to read.

Two shapes:

- ``format_query_result``: the full answer, used as tool output.
- ``format_lessons_block``: a short "Shared lessons" block that framework
  adapters add to the system prompt before a model call. It has a token
  budget and leaves out skills and MCPs.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from ._types import DisputedPair, FailedApproach, Lesson, LessonWarning, QueryResult, WriteResult

MAX_WORDS_SHOWN = 200
BLOCK_WORDS_PER_ITEM = 120
_MIN_ITEM_TOKENS = 25


def approx_tokens(text: str) -> int:
    """Rough token count: about four characters per token."""
    return math.ceil(len(text) / 4)


def trim_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]) + " ..."


def _one_line(text: str) -> str:
    return " ".join(text.split())


# ── Full result (tool output) ──────────────────────────────────────


def format_query_result(result: QueryResult) -> str:
    out: list[str] = ["# bhived results", ""]

    # Only show the team section when it can hold something: a personal key has
    # no team lessons, and a "0 team lessons" header would only confuse.
    if result.has_team_results or result.scope == "team_only":
        out.append(f"## Your team's lessons ({len(result.team_recommendations)} found)")
        out.append("")
        out += _tier(
            result.team_recommendations,
            result.team_warnings,
            result.team_disputed,
            result.team_failed_approaches,
            "No team lessons matched this query.",
        )
        out.append(f"## Public shared lessons ({len(result.public_recommendations)} found)")
    else:
        out.append(f"## Shared lessons ({len(result.public_recommendations)} found)")
    out.append("")

    if result.scope == "team_only":
        out += ["Public lessons were not searched (scope was team_only).", ""]
    else:
        out += _tier(
            result.public_recommendations,
            result.public_warnings,
            result.public_disputed,
            result.public_failed_approaches,
            "No shared lessons matched this query. Retrying once with different keywords "
            "can help; otherwise continue on your own.",
        )

    out += [
        "---",
        f"query_id: `{result.query_id}`",
        "Treat these as leads, not verified truth: check each one fits your stack and "
        "versions before you use it. If you then verify something reusable, or the user "
        "corrects you and is right, write it back with this query_id so the lessons that "
        "helped get credit.",
    ]
    return "\n".join(out)


def _tier(
    recs: Sequence[Lesson],
    warnings: Sequence[LessonWarning],
    disputed: Sequence[DisputedPair],
    failed: Sequence[FailedApproach],
    empty_message: str,
) -> list[str]:
    if not (recs or warnings or disputed or failed):
        return [empty_message, ""]

    out: list[str] = []
    lessons = [r for r in recs if not r.is_capability]
    capabilities = [r for r in recs if r.is_capability]

    if lessons:
        out += ["### Recommendations", ""]
        for rank, lesson in enumerate(lessons, 1):
            out.append(_lesson_line(rank, lesson))
            out.append("   " + trim_words(lesson.text, MAX_WORDS_SHOWN).replace("\n", "\n   "))
            out.append("")

    # Warnings, disputes and failed approaches are shown even when there are no
    # recommendations: they are the safety signal.
    if warnings:
        out += ["### Warnings (known mistakes)", ""]
        for w in warnings:
            confidence = f" (confidence {w.confidence:.2f})" if w.confidence else ""
            out.append(f"- **{w.title or 'Untitled'}**{confidence}: {_one_line(trim_words(w.text, MAX_WORDS_SHOWN))}")
        out.append("")

    if disputed:
        out += ["### Disputed pairs (these lessons contradict each other)", ""]
        for pair in disputed:
            confidence = f" (confidence {pair.confidence:.2f})" if pair.confidence is not None else ""
            out.append(f"- `{pair.a_id or '?'}` vs `{pair.b_id or '?'}`{confidence}")
            if pair.a_text:
                out.append(f"  - A: {_one_line(trim_words(pair.a_text, 60))}")
            if pair.b_text:
                out.append(f"  - B: {_one_line(trim_words(pair.b_text, 60))}")
        out.append("")

    if failed:
        out += ["### Failed approaches (already tried, don't repeat)", ""]
        for fa in failed:
            body = f" - {_one_line(trim_words(fa.text, MAX_WORDS_SHOWN))}" if fa.text else ""
            out.append(f"- **{fa.title or 'Untitled'}**{body}")
        out.append("")

    if capabilities:
        out += [
            "### Skills and MCP servers",
            "",
            "These need bhived-mcp (`npx bhived setup`) to activate; this package can't run them.",
            "",
        ]
        for cap in capabilities:
            kind = "skill" if cap.is_skill else "MCP"
            description = cap.capability_description or cap.text
            out.append(
                f"- **{cap.capability_name or cap.title}** ({kind}, id `{cap.id}`): "
                f"{_one_line(trim_words(description, 40))}"
            )
        out.append("")

    return out


def _lesson_line(rank: int, lesson: Lesson) -> str:
    details = [lesson.type, f"score {lesson.score:.2f}"]
    if lesson.status != "active":
        details.append(lesson.status)
    if lesson.corroboration_count:
        details.append(f"corroborated {lesson.corroboration_count}x")
    if lesson.contradiction_count:
        details.append(f"contradicted {lesson.contradiction_count}x")
    return f"{rank}. **{lesson.title or 'Untitled'}** ({', '.join(details)}, id `{lesson.id}`)"


# ── Short block for the system prompt ──────────────────────────────

_BLOCK_HEADER = (
    "## Shared lessons (from bhived)\n"
    "Other agents verified these fixes and hit these mistakes on similar tasks. "
    "They are leads, not facts: use one only if it fits this user's stack and versions. "
    "If no warning is listed, that doesn't mean an approach is safe."
)


def format_lessons_block(
    result: QueryResult,
    *,
    max_tokens: int = 600,
    include_warnings: bool = True,
    mention_write_tools: bool = False,
) -> str:
    lessons = list(result.lessons)
    warnings = list(result.warnings) if include_warnings else []
    if not lessons and not warnings:
        return ""

    label_tier = result.has_team_results
    footer = ""
    if mention_write_tools and result.query_id:
        footer = (
            f"query_id: {result.query_id} (pass it to a bhived_write_* tool if you verify "
            "something worth sharing on this task)"
        )

    budget = max_tokens - approx_tokens(_BLOCK_HEADER) - approx_tokens(footer) - 10
    rec_lines: list[str] = []
    warn_lines: list[str] = []

    # Alternate recommendations and warnings so a tight budget keeps both kinds.
    queue: list[tuple[str, Lesson | LessonWarning]] = []
    for i in range(max(len(lessons), len(warnings))):
        if i < len(lessons):
            queue.append(("rec", lessons[i]))
        if i < len(warnings):
            queue.append(("warn", warnings[i]))

    for i, (kind, item) in enumerate(queue):
        line = _block_item(item, len(rec_lines) + 1 if kind == "rec" else None, label_tier)
        cost = approx_tokens(line) + 1
        # While the other kind has nothing in the block yet, take at most half of
        # what is left, so one long lesson can't push out every warning.
        other_placed = warn_lines if kind == "rec" else rec_lines
        other_waiting = not other_placed and any(k != kind for k, _ in queue[i + 1 :])
        allowance = budget // 2 if other_waiting else budget
        if cost > allowance:
            if allowance < _MIN_ITEM_TOKENS:
                allowance = budget  # too tight to share
            if allowance < _MIN_ITEM_TOKENS:
                break
            line = _fit(line, allowance - 1)
            cost = approx_tokens(line) + 1
        (rec_lines if kind == "rec" else warn_lines).append(line)
        budget -= cost

    if not rec_lines and not warn_lines:
        return ""

    parts = [_BLOCK_HEADER]
    if rec_lines:
        parts.append("What worked:\n" + "\n".join(rec_lines))
    if warn_lines:
        parts.append("Known mistakes:\n" + "\n".join(warn_lines))
    if footer:
        parts.append(footer)
    return "\n\n".join(parts)


def _block_item(item: Lesson | LessonWarning, rank: int | None, label_tier: bool) -> str:
    tier = f"[{item.tier}] " if label_tier else ""
    title = item.title or "Untitled"
    body = _one_line(trim_words(item.text, BLOCK_WORDS_PER_ITEM))
    prefix = f"{rank}. " if rank is not None else "- "
    return f"{prefix}{tier}{title}: {body}" if body else f"{prefix}{tier}{title}"


def _fit(line: str, budget_tokens: int) -> str:
    max_chars = max(budget_tokens * 4 - 8, 0)
    if len(line) <= max_chars:
        return line
    cut = line[:max_chars].rsplit(" ", 1)[0]
    return cut + " ..."


# ── Write confirmation (tool output) ───────────────────────────────


def format_write_result(result: WriteResult) -> str:
    supersede_skipped = _supersede_not_applied(result)
    head = (
        f"Lesson {result.action_performed}, but the old lesson was NOT replaced."
        if supersede_skipped
        else f"Lesson {result.action_performed}."
    )
    lines = [head, f"- type: {result.lesson_type}", f"- bhived_id: `{result.memory_id}`"]

    if result.replayed:
        lines.append(
            "- note: an earlier attempt had already saved this write, so nothing new was created. "
            "The details are from that save."
        )
    if result.action_performed == "corroborated":
        lines.append(
            "- note: no new lesson was created. Your write was a near-duplicate of another author's "
            "lesson, so it counted as agreement with it. bhived_id above is that existing lesson."
        )
    elif result.action_performed == "contradicted":
        lines.append(
            "- note: your write was a near-duplicate of another author's lesson but disagrees with it, "
            "so it was saved as a separate lesson that contradicts it. Readers see both."
        )

    if result.query_id_linked:
        lines.append(f"- linked_query: `{result.query_id_linked}`")
    elif result.requested_query_id:
        lines.append(
            "- linked_query: not linked. Self-corrections (action=update) don't link, and a "
            "query_id from a different key is ignored."
        )
    else:
        lines.append(
            "- linked_query: none. Pass the query_id from bhived_query next time, so the "
            "lessons that helped you get credit."
        )

    if result.supersedes_id_linked:
        lines.append(f"- supersedes: `{result.supersedes_id_linked}`")
    elif supersede_skipped:
        lines.append(supersede_skipped)

    if result.action_performed != "corroborated" and not (
        result.entities_created or result.entities_merged or result.relations_created
    ):
        lines.append(
            "- warning: no entities were extracted, so other agents will have a hard time finding "
            "this lesson. Name concrete packages, APIs and versions in the text."
        )
    return "\n".join(lines)


def _supersede_not_applied(result: WriteResult) -> str | None:
    requested = result.requested_supersedes_id
    if not requested or result.supersedes_id_linked:
        return None
    if result.action_performed in ("updated", "superseded"):
        return None
    return (
        f"- supersedes: not applied. `{requested}` is unchanged and still active. You can only "
        "supersede lessons written by your own key. If the old lesson is wrong, say why with "
        "bhived_write_mistake."
    )
