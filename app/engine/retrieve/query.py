"""Safe FTS5 query construction for user text.

The user string is never interpolated raw. Tokens are quoted, FTS operators
are dropped, and citation-shaped phrases are added as extra OR terms so
bm25 prefers them. Diacritics stay in the token text; the unicode61
tokenizer folds them at match time.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Letters and digits. Underscore and punctuation are separators, which also
# strips quotes, *, parentheses, and column-filter colons.
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_OPERATORS = frozenset({"and", "or", "not", "near"})
_SLASH_RE = re.compile(r"\b(\d{2,4})\s*/\s*(\d{4})\b")
_ARTIGO_RE = re.compile(
    r"(?i)\bart(?:igo|igos)?\.?\s*(?:n\.?\s*[ºo°.]?\s*)?(\d{1,4})\b"
)

_MAX_TOKENS = 64
_PHRASE_BONUS = 10.0


@dataclass(frozen=True)
class PreparedQuery:
    """A MATCH expression plus the citation phrases used to boost hits."""

    match: str | None
    slash_phrases: tuple[str, ...]
    artigo_numbers: tuple[str, ...]


def build_match_query(user_query: str) -> PreparedQuery:
    """Turn free text into a quoted OR query. ``match`` is None when empty."""

    if not user_query or not user_query.strip():
        return PreparedQuery(None, (), ())

    slash_phrases: list[str] = []
    seen_slash: set[str] = set()
    for left, right in _SLASH_RE.findall(user_query):
        phrase = f"{left}/{right}"
        if phrase not in seen_slash:
            seen_slash.add(phrase)
            slash_phrases.append(phrase)

    artigo_numbers: list[str] = []
    seen_artigo: set[str] = set()
    for number in _ARTIGO_RE.findall(user_query):
        if number not in seen_artigo:
            seen_artigo.add(number)
            artigo_numbers.append(number)

    tokens: list[str] = []
    seen_tokens: set[str] = set()
    for raw in _TOKEN_RE.findall(user_query):
        if raw.casefold() in _OPERATORS:
            continue
        key = _fold(raw)
        if not key or key in seen_tokens:
            continue
        seen_tokens.add(key)
        tokens.append(raw)
        if len(tokens) >= _MAX_TOKENS:
            break

    parts: list[str] = [_quote_term(token) for token in tokens]
    seen_parts = set(parts)
    for phrase in slash_phrases:
        left, right = phrase.split("/", 1)
        _add_part(parts, seen_parts, f'"{left} {right}"')
    for number in artigo_numbers:
        _add_part(parts, seen_parts, f'"artigo {number}"')

    if not parts:
        return PreparedQuery(None, tuple(slash_phrases), tuple(artigo_numbers))
    return PreparedQuery(
        " OR ".join(parts),
        tuple(slash_phrases),
        tuple(artigo_numbers),
    )


def phrase_bonus(text: str, prepared: PreparedQuery) -> float:
    """Extra rank for a real '261/2004' or 'artigo 7' hit inside the passage.

    Ranking only. Quote verification must not use this fold.
    """

    if not prepared.slash_phrases and not prepared.artigo_numbers:
        return 0.0
    folded = _fold(text)
    bonus = 0.0
    for phrase in prepared.slash_phrases:
        left, right = phrase.split("/", 1)
        if re.search(rf"\b{left}\s*/\s*{right}\b", folded):
            bonus += _PHRASE_BONUS
    for number in prepared.artigo_numbers:
        if re.search(rf"\bartigos?\s+{re.escape(number)}\b", folded):
            bonus += _PHRASE_BONUS
    return bonus


def _add_part(parts: list[str], seen: set[str], part: str) -> None:
    if part not in seen:
        seen.add(part)
        parts.append(part)


def _quote_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    collapsed = re.sub(r"\s+", " ", without_marks)
    return collapsed.casefold()
