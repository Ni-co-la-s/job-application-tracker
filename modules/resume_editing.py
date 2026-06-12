"""Deterministic search/replacement helpers for LaTeX resume edits."""

from dataclasses import dataclass
import re


@dataclass
class ApplyResult:
    """Result of applying a single edit."""

    status: str
    message: str


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
            "applied_exact", "Applied by exact string match."
        )
    if exact_count > 1:
        return source, ApplyResult(
            "manual_required", "Exact search matched multiple locations."
        )

    pattern = _whitespace_tolerant_pattern(search)
    matches = list(re.finditer(pattern, source, flags=re.DOTALL))
    if len(matches) != 1:
        message = (
            "Whitespace-tolerant search did not match."
            if not matches
            else "Whitespace-tolerant search matched multiple locations."
        )
        return source, ApplyResult("manual_required", message)

    match = matches[0]
    updated = source[: match.start()] + replacement + source[match.end() :]
    return updated, ApplyResult(
        "applied_whitespace", "Applied by deterministic whitespace-tolerant match."
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
                    "apply_status": "rejected",
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
    return any(result.get("apply_status") == "manual_required" for result in results)


def _whitespace_tolerant_pattern(search: str) -> str:
    r"""Escape search text and replace escaped whitespace runs with ``\s+``."""
    parts = re.split(r"\s+", search.strip())
    return r"\s+".join(re.escape(part) for part in parts if part)
