"""Literal-substring redaction helpers for resume tailoring."""


def build_redaction_map(strings: list[str]) -> dict[str, str]:
    """Build an ordered literal -> opaque token redaction map.

    Blank strings are ignored and duplicates are removed while preserving the
    first occurrence. Tokens are intentionally opaque to the LLM and stable for
    a single generation run only.
    """
    mapping: dict[str, str] = {}
    for value in strings:
        literal = value.strip()
        if not literal or literal in mapping:
            continue
        mapping[literal] = f"[[REDACT_{len(mapping) + 1}]]"
    return mapping


def redact(text: str, mapping: dict[str, str]) -> str:
    """Replace configured literals with opaque tokens, longest literals first."""
    redacted = text
    for literal, token in sorted(
        mapping.items(), key=lambda item: len(item[0]), reverse=True
    ):
        redacted = redacted.replace(literal, token)
    return redacted


def restore(text: str, mapping: dict[str, str]) -> str:
    """Restore opaque tokens back to their original literal values."""
    restored = text
    for literal, token in mapping.items():
        restored = restored.replace(token, literal)
    return restored
