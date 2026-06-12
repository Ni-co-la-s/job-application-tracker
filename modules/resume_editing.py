"""Deterministic search/replacement helpers for LaTeX resume edits."""

from dataclasses import dataclass
import re

STATUS_APPLIED_EXACT = "applied_exact"
STATUS_APPLIED_NORMALIZED_WHITESPACE = "applied_normalized_whitespace"
STATUS_MANUAL_REQUIRED = "manual_required"
STATUS_REJECTED = "rejected"


@dataclass
class ApplyResult:
    """Result of applying a single edit."""

    status: str
    message: str
    start: int | None = None
    end: int | None = None


@dataclass
class MatchResult:
    """Result of matching a search string without applying it."""

    status: str
    message: str
    start: int | None = None
    end: int | None = None
    start_line: int | None = None
    end_line: int | None = None


def match_edit_once(source: str, search: str) -> MatchResult:
    """Match one deterministic edit search against source without replacing it."""
    exact_matches = list(_literal_spans(source, search)) if search else []
    if len(exact_matches) == 1:
        start, end = exact_matches[0]
        start_line, end_line = _line_range_for_span(source, start, end)
        return MatchResult(
            STATUS_APPLIED_EXACT,
            "Matched by exact string match.",
            start,
            end,
            start_line,
            end_line,
        )
    if len(exact_matches) > 1:
        return MatchResult(
            STATUS_MANUAL_REQUIRED, "Exact search matched multiple locations."
        )

    pattern = _whitespace_tolerant_pattern(search)
    matches = list(re.finditer(pattern, source, flags=re.DOTALL))
    if len(matches) != 1:
        message = (
            "Whitespace-tolerant search did not match."
            if not matches
            else "Whitespace-tolerant search matched multiple locations."
        )
        return MatchResult(STATUS_MANUAL_REQUIRED, message)

    match = matches[0]
    start_line, end_line = _line_range_for_span(source, match.start(), match.end())
    return MatchResult(
        STATUS_APPLIED_NORMALIZED_WHITESPACE,
        "Matched by deterministic whitespace-tolerant search.",
        match.start(),
        match.end(),
        start_line,
        end_line,
    )


def apply_edit_once(
    source: str, search: str, replacement: str
) -> tuple[str, ApplyResult]:
    r"""Apply one deterministic edit to source.

    Exact match is attempted first. If it is not found, a regex is built from
    the escaped search string with whitespace runs replaced by ``\s+``. The
    regex edit is applied only when it matches exactly once.
    """
    exact_count = source.count(search)
    if exact_count == 1:
        return source.replace(search, replacement, 1), ApplyResult(
            STATUS_APPLIED_EXACT, "Applied by exact string match."
        )
    if exact_count > 1:
        return source, ApplyResult(
            STATUS_MANUAL_REQUIRED, "Exact search matched multiple locations."
        )

    pattern = _whitespace_tolerant_pattern(search)
    matches = list(re.finditer(pattern, source, flags=re.DOTALL))
    if len(matches) != 1:
        message = (
            "Whitespace-tolerant search did not match."
            if not matches
            else "Whitespace-tolerant search matched multiple locations."
        )
        return source, ApplyResult(STATUS_MANUAL_REQUIRED, message)

    match = matches[0]
    updated = source[: match.start()] + replacement + source[match.end() :]
    return updated, ApplyResult(
        STATUS_APPLIED_NORMALIZED_WHITESPACE,
        "Applied by deterministic whitespace-tolerant match.",
        match.start(),
        match.end(),
    )


def apply_approved_edits(source: str, edits: list[dict]) -> tuple[str, list[dict]]:
    """Apply all accepted edits and return updated source plus result metadata."""
    updated_source = source
    results: list[dict] = []

    for index, edit in enumerate(edits):
        if not edit.get("accepted"):
            results.append(
                {
                    **edit,
                    "edit_index": index,
                    "apply_status": STATUS_REJECTED,
                    "apply_message": "Rejected.",
                }
            )
            continue

        updated_source, result = apply_edit_once(
            updated_source,
            edit.get("search", ""),
            edit.get("replacement", ""),
        )
        results.append(
            {
                **edit,
                "edit_index": index,
                "apply_status": result.status,
                "apply_message": result.message,
            }
        )

    return updated_source, results


def has_manual_required(results: list[dict]) -> bool:
    """Return True if any accepted edit could not be auto-applied."""
    return any(
        result.get("apply_status") == STATUS_MANUAL_REQUIRED for result in results
    )


def _literal_spans(source: str, search: str):
    """Yield all non-overlapping literal match spans."""
    start = 0
    while True:
        index = source.find(search, start)
        if index == -1:
            break
        end = index + len(search)
        yield index, end
        start = end


def _line_range_for_span(source: str, start: int, end: int) -> tuple[int, int]:
    """Return 1-indexed full-file line range for a character span."""
    start_line = source.count("\n", 0, start) + 1
    end_index = max(start, end - 1)
    end_line = source.count("\n", 0, end_index) + 1
    return start_line, end_line


def _whitespace_tolerant_pattern(search: str) -> str:
    r"""Escape search text and replace escaped whitespace runs with ``\s+``."""
    parts = re.split(r"\s+", search.strip())
    return r"\s+".join(re.escape(part) for part in parts if part)
