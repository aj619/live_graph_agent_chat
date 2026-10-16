"""Split extracted document text into chunks no longer than a character limit (plan §6.5).

Each returned chunk becomes one Graphiti episode. The limit is passed in by the
caller (it comes from INGEST_CHUNK_CHARS in app.config); this module reads no
settings itself.

Rules:
- A paragraph boundary is one or more blank lines (a line that is empty or
  contains only whitespace). A single newline inside a paragraph is kept as is,
  because extracted PDF and DOCX text often hard-wraps lines mid-sentence.
- Paragraphs are stripped of leading and trailing whitespace. Paragraphs that are
  empty after stripping are dropped.
- Consecutive paragraphs are grouped into one chunk with a blank line between
  them, for as long as the chunk stays within the limit. A new chunk starts only
  when the next paragraph does not fit.
- A paragraph longer than the limit is hard-split. The split point is the last
  whitespace character at or before the limit. If the window has no whitespace
  (for example, one very long token), the split is made exactly at the limit.
  The whitespace at a split point is dropped.
- Every returned chunk has length <= limit. Joining the chunks with a blank line
  reproduces all non-whitespace text in the input, in order.

The function is pure: no I/O, no logging, no global state, and no imports
beyond the standard library.
"""

import re

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_CHUNK_SEPARATOR = "\n\n"


def chunk_text(text: str, limit: int) -> list[str]:
    """Return the ordered chunks of text, each at most limit characters long.

    Empty or whitespace-only text returns an empty list. limit must be at least 1.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")

    units: list[str] = []
    for paragraph in _PARAGRAPH_BREAK.split(text):
        stripped = paragraph.strip()
        if not stripped:
            continue
        units.extend(_hard_split(stripped, limit))

    chunks: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
        elif len(current) + len(_CHUNK_SEPARATOR) + len(unit) <= limit:
            current = current + _CHUNK_SEPARATOR + unit
        else:
            chunks.append(current)
            current = unit
    if current:
        chunks.append(current)
    return chunks


def _hard_split(paragraph: str, limit: int) -> list[str]:
    """Split one stripped, non-empty paragraph into pieces of at most limit characters.

    The paragraph must start with a non-whitespace character. Each step removes at
    least one character, so the loop always ends.
    """
    pieces: list[str] = []
    rest = paragraph
    while len(rest) > limit:
        window = rest[: limit + 1]
        cut = limit
        for index in range(len(window) - 1, 0, -1):
            if window[index].isspace():
                cut = index
                break
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return pieces
