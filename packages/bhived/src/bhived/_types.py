"""Result objects for queries and writes.

Parsing is lenient on purpose: depending on the retrieval pipeline the API may
leave out fields (or send ``memory_id`` instead of ``id``), so every field
except ``query_id`` has a default. The untouched response is kept in ``raw``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Tier = Literal["team", "public"]


def _str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _int(value: Any) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


@dataclass(frozen=True)
class Lesson:
    """One ranked result: a shared lesson, or a skill/MCP capability."""

    id: str
    title: str
    text: str
    type: str
    """``instruction``, ``mistake``, ``update`` or ``note``."""
    status: str
    """``active``, ``archived``, ``disputed`` or ``superseded``."""
    score: float
    """Retrieval score. It measures relevance, not correctness."""
    tier: Tier
    corroboration_count: int = 0
    contradiction_count: int = 0
    is_skill: bool = False
    is_mcp: bool = False
    capability_name: str | None = None
    capability_description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def is_capability(self) -> bool:
        """True for skills and MCP servers, which need bhived-mcp to activate."""
        return self.is_skill or self.is_mcp

    @classmethod
    def from_api(cls, data: dict[str, Any], tier: Tier) -> Lesson:
        is_skill = bool(data.get("has_skill")) and isinstance(data.get("skill_meta"), dict)
        is_mcp = not is_skill and bool(data.get("has_mcp")) and isinstance(data.get("mcp_meta"), dict)
        meta = data.get("skill_meta") if is_skill else data.get("mcp_meta") if is_mcp else None
        return cls(
            id=_str(data.get("id")) or _str(data.get("memory_id")) or "unknown",
            title=_str(data.get("title")),
            text=_str(data.get("text")),
            type=_str(data.get("type"), "note"),
            status=_str(data.get("status"), "active"),
            score=_num(data.get("score")),
            tier=tier,
            corroboration_count=_int(data.get("corroboration_count")),
            contradiction_count=_int(data.get("contradiction_count")),
            is_skill=is_skill,
            is_mcp=is_mcp,
            capability_name=_opt_str(meta.get("name")) if meta else None,
            capability_description=_opt_str(meta.get("description")) if meta else None,
            raw=data,
        )


@dataclass(frozen=True)
class LessonWarning:
    """A known mistake that is relevant to the query."""

    id: str
    title: str
    text: str
    confidence: float
    tier: Tier
    contradicts_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, data: dict[str, Any], tier: Tier) -> LessonWarning:
        return cls(
            id=_str(data.get("id")) or _str(data.get("memory_id")) or "unknown",
            title=_str(data.get("title")),
            text=_str(data.get("text")),
            confidence=_num(data.get("confidence")),
            tier=tier,
            contradicts_id=_opt_str(data.get("contradicts_memory_id")),
            raw=data,
        )


@dataclass(frozen=True)
class DisputedPair:
    """Two lessons that contradict each other."""

    a_id: str | None
    a_text: str
    b_id: str | None
    b_text: str
    confidence: float | None
    tier: Tier
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, data: dict[str, Any], tier: Tier) -> DisputedPair:
        # The live API sends a flat shape; older servers nested the two lessons.
        a = data.get("memory_a") if isinstance(data.get("memory_a"), dict) else {}
        b = data.get("memory_b") if isinstance(data.get("memory_b"), dict) else {}
        confidence = data.get("confidence")
        return cls(
            a_id=_opt_str(data.get("memory_a_id")) or _opt_str(a.get("id")) or _opt_str(a.get("memory_id")),
            a_text=_str(data.get("memory_a_text")) or _str(a.get("text")),
            b_id=_opt_str(data.get("memory_b_id")) or _opt_str(b.get("id")) or _opt_str(b.get("memory_id")),
            b_text=_str(data.get("memory_b_text")) or _str(b.get("text")),
            confidence=_num(confidence) if confidence is not None else None,
            tier=tier,
            raw=data,
        )


@dataclass(frozen=True)
class FailedApproach:
    """Something that was already tried and abandoned."""

    id: str | None
    title: str
    text: str
    tier: Tier
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, data: dict[str, Any], tier: Tier) -> FailedApproach:
        return cls(
            id=_opt_str(data.get("id")) or _opt_str(data.get("memory_id")),
            title=_str(data.get("title")),
            text=_str(data.get("reason")) or _str(data.get("text")),
            tier=tier,
            raw=data,
        )


@dataclass(frozen=True)
class QueryResult:
    """The answer to ``POST /v2/query``.

    Team and public results stay separate. With a personal key the team
    lists are always empty.
    """

    query_id: str
    team_recommendations: tuple[Lesson, ...] = ()
    public_recommendations: tuple[Lesson, ...] = ()
    team_warnings: tuple[LessonWarning, ...] = ()
    public_warnings: tuple[LessonWarning, ...] = ()
    team_disputed: tuple[DisputedPair, ...] = ()
    public_disputed: tuple[DisputedPair, ...] = ()
    team_failed_approaches: tuple[FailedApproach, ...] = ()
    public_failed_approaches: tuple[FailedApproach, ...] = ()
    scope: str | None = None
    """The scope this query was sent with (None means the server default)."""
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, data: dict[str, Any], scope: str | None = None) -> QueryResult:
        def tier_items(kind: type, name: str, tier: Tier) -> tuple[Any, ...]:
            return tuple(kind.from_api(item, tier) for item in _dicts(data.get(f"{tier}_{name}")))

        return cls(
            query_id=_str(data.get("query_id")),
            team_recommendations=tier_items(Lesson, "recommendations", "team"),
            public_recommendations=tier_items(Lesson, "recommendations", "public"),
            team_warnings=tier_items(LessonWarning, "warnings", "team"),
            public_warnings=tier_items(LessonWarning, "warnings", "public"),
            team_disputed=tier_items(DisputedPair, "disputed", "team"),
            public_disputed=tier_items(DisputedPair, "disputed", "public"),
            team_failed_approaches=tier_items(FailedApproach, "failed_approaches", "team"),
            public_failed_approaches=tier_items(FailedApproach, "failed_approaches", "public"),
            scope=scope,
            raw=data,
        )

    @property
    def recommendations(self) -> tuple[Lesson, ...]:
        """Team results first, then public."""
        return self.team_recommendations + self.public_recommendations

    @property
    def lessons(self) -> tuple[Lesson, ...]:
        """Recommendations that are lessons, not skills or MCPs."""
        return tuple(item for item in self.recommendations if not item.is_capability)

    @property
    def capabilities(self) -> tuple[Lesson, ...]:
        """Recommended skills and MCP servers."""
        return tuple(item for item in self.recommendations if item.is_capability)

    @property
    def warnings(self) -> tuple[LessonWarning, ...]:
        return self.team_warnings + self.public_warnings

    @property
    def disputed(self) -> tuple[DisputedPair, ...]:
        return self.team_disputed + self.public_disputed

    @property
    def failed_approaches(self) -> tuple[FailedApproach, ...]:
        return self.team_failed_approaches + self.public_failed_approaches

    @property
    def has_team_results(self) -> bool:
        return bool(
            self.team_recommendations or self.team_warnings or self.team_disputed or self.team_failed_approaches
        )

    @property
    def is_empty(self) -> bool:
        return not (self.recommendations or self.warnings or self.disputed or self.failed_approaches)

    def to_markdown(self) -> str:
        """Full results as Markdown, written for an LLM to read (tool output)."""
        from ._format import format_query_result

        return format_query_result(self)

    def as_context(
        self,
        *,
        max_tokens: int = 600,
        include_warnings: bool = True,
        mention_write_tools: bool = False,
    ) -> str:
        """A short "Shared lessons" block for a system prompt. Empty when nothing matched.

        ``max_tokens`` is approximate (about four characters per token).
        Skills and MCPs are left out, because they need bhived-mcp to run.
        """
        from ._format import format_lessons_block

        return format_lessons_block(
            self,
            max_tokens=max_tokens,
            include_warnings=include_warnings,
            mention_write_tools=mention_write_tools,
        )


@dataclass(frozen=True)
class WriteResult:
    """The answer to ``POST /v1/memories``."""

    memory_id: str
    action_performed: str
    """``created``, ``updated``, ``superseded``, ``corroborated`` or ``contradicted``."""
    lesson_type: str
    query_id_linked: str | None = None
    supersedes_id_linked: str | None = None
    entities_created: int = 0
    entities_merged: int = 0
    relations_created: int = 0
    causal_relations: int = 0
    corroborations_created: int = 0
    contradictions_created: int = 0
    replayed: bool = False
    """True when an earlier attempt with the same idempotency key had already saved it."""
    requested_query_id: str | None = None
    requested_supersedes_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def bhived_id(self) -> str:
        """The lesson's id (the same value as ``memory_id``)."""
        return self.memory_id

    @classmethod
    def from_api(
        cls,
        data: dict[str, Any],
        *,
        lesson_type: str,
        replayed: bool = False,
        requested_query_id: str | None = None,
        requested_supersedes_id: str | None = None,
    ) -> WriteResult:
        return cls(
            memory_id=_str(data.get("memory_id")),
            action_performed=_str(data.get("action_performed"), "created"),
            lesson_type=lesson_type,
            query_id_linked=_opt_str(data.get("query_id_linked")),
            supersedes_id_linked=_opt_str(data.get("supersedes_id_linked")),
            entities_created=_int(data.get("entities_created")),
            entities_merged=_int(data.get("entities_merged")),
            relations_created=_int(data.get("relations_created")),
            causal_relations=_int(data.get("causal_relations")),
            corroborations_created=_int(data.get("corroborations_created")),
            contradictions_created=_int(data.get("contradictions_created")),
            replayed=replayed,
            requested_query_id=requested_query_id,
            requested_supersedes_id=requested_supersedes_id,
            raw=data,
        )

    def to_markdown(self) -> str:
        """A short confirmation for an LLM to read (tool output)."""
        from ._format import format_write_result

        return format_write_result(self)
