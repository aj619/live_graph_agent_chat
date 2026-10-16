"""Boundary and limit tests for app.chunking.chunk_text (plan §6.5).

chunk_text is pure: no settings, no I/O, no fakes needed. Expected outputs in
these tests were worked out by hand from the rules in the module docstring.
"""

import sys
from pathlib import Path

import pytest

# The backend project is not installed (package = false), so `backend/` is put
# on sys.path here so that `app` can be imported when pytest runs this file alone.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chunking import chunk_text  # noqa: E402


def _non_whitespace(text: str) -> str:
    return "".join(text.split())


# --- empty and whitespace-only input ---------------------------------------


def test_empty_string_returns_no_chunks() -> None:
    assert chunk_text("", 10) == []


def test_whitespace_only_input_returns_no_chunks() -> None:
    assert chunk_text("   \n\n\t  \n \n", 10) == []


# --- single paragraph, relative to the limit -------------------------------


def test_text_shorter_than_limit_returns_one_stripped_chunk() -> None:
    assert chunk_text("  hello world  ", 50) == ["hello world"]


def test_paragraph_exactly_at_limit_is_not_split() -> None:
    text = "x" * 10
    assert chunk_text(text, 10) == ["x" * 10]


def test_paragraph_one_over_limit_is_hard_split_into_two_pieces() -> None:
    # 11 characters, no whitespace: cut exactly at the limit -> "x"*10 and "x".
    chunks = chunk_text("x" * 11, 10)
    assert chunks == ["x" * 10, "x"]
    assert all(len(chunk) <= 10 for chunk in chunks)


def test_hard_split_prefers_last_whitespace_at_or_before_limit() -> None:
    # "aaa bbb ccc" (11 chars), limit 7. Window is "aaa bbb " and the last
    # whitespace is at index 7, so the cut gives "aaa bbb" and "ccc".
    # "aaa bbb" (7) plus "ccc" would be 12, which is over 7, so they stay apart.
    assert chunk_text("aaa bbb ccc", 7) == ["aaa bbb", "ccc"]


def test_hard_split_uses_whitespace_inside_window_not_only_at_limit() -> None:
    # "aaaa bbbbbbbbbb" (15 chars), limit 10. The window "aaaa bbbbbb" has its
    # last whitespace at index 4, so the first piece is "aaaa". The remaining
    # "bbbbbbbbbb" is exactly 10 characters and stays whole.
    # Then "aaaa" + "\n\n" + "bbbbbbbbbb" is 16 (over 10), so the groups are
    # ["aaaa", "bbbbbbbbbb", "cc"], since "bbbbbbbbbb" + "\n\n" + "cc" is 14.
    assert chunk_text("aaaa bbbbbbbbbb\n\ncc", 10) == ["aaaa", "bbbbbbbbbb", "cc"]


# --- greedy grouping of paragraphs -----------------------------------------


def test_small_paragraphs_that_fit_together_are_grouped_into_one_chunk() -> None:
    text = "one\n\ntwo\n\nthree"
    assert chunk_text(text, 100) == ["one\n\ntwo\n\nthree"]


def test_grouping_is_greedy_and_fewer_chunks_than_paragraphs() -> None:
    # Five paragraphs of 7 characters each, limit 20.
    # "p1-aaaa" + sep + "p2-bbbb" = 7 + 2 + 7 = 16 (fits).
    # Adding "p3-cccc" would be 16 + 2 + 7 = 25 (over), so a new chunk starts.
    # "p3-cccc" + sep + "p4-dddd" = 16 (fits).
    # Adding "p5-eeee" would be 25 (over), so "p5-eeee" is alone.
    text = "p1-aaaa\n\np2-bbbb\n\np3-cccc\n\np4-dddd\n\np5-eeee"
    chunks = chunk_text(text, 20)
    assert chunks == ["p1-aaaa\n\np2-bbbb", "p3-cccc\n\np4-dddd", "p5-eeee"]
    assert len(chunks) < 5
    assert all(len(chunk) <= 20 for chunk in chunks)


def test_paragraph_that_does_not_fit_starts_a_new_chunk() -> None:
    # "aaaa" (4) + sep + "bbbbbb" (6) = 12 > 10, so "bbbbbb" starts chunk two.
    # "bbbbbb" + sep + "cc" = 10 <= 10, so "cc" joins it.
    assert chunk_text("aaaa\n\nbbbbbb\n\ncc", 10) == ["aaaa", "bbbbbb\n\ncc"]


# --- blank lines and surrounding whitespace --------------------------------


def test_leading_and_trailing_blank_lines_do_not_create_empty_chunks() -> None:
    text = "\n\n\n\n   \n  Hello world  \n\n\n\n  \n\n"
    chunks = chunk_text(text, 50)
    assert chunks == ["Hello world"]
    assert "" not in chunks


def test_single_newline_inside_paragraph_is_kept() -> None:
    # A single newline is not a paragraph break, so the two lines stay together.
    assert chunk_text("line one\nline two", 50) == ["line one\nline two"]


# --- degenerate limits ------------------------------------------------------


def test_limit_one_splits_every_character_into_its_own_chunk() -> None:
    chunks = chunk_text("abc", 1)
    assert chunks == ["a", "b", "c"]
    assert all(len(chunk) == 1 for chunk in chunks)


def test_limit_one_skips_whitespace_and_keeps_every_non_space_character() -> None:
    text = "ab cd"
    chunks = chunk_text(text, 1)
    assert chunks == ["a", "b", "c", "d"]
    assert all(len(chunk) == 1 for chunk in chunks)
    assert "".join(chunks) == _non_whitespace(text)


@pytest.mark.parametrize("limit", [0, -5])
def test_non_positive_limit_raises_value_error(limit: int) -> None:
    with pytest.raises(ValueError):
        chunk_text("some text", limit)


# --- unicode and multi-byte characters -------------------------------------


def test_emoji_are_counted_as_single_characters() -> None:
    # Seven emoji are seven code points, so len() is 7 and the limit is in code
    # points. Limit 3 gives 3 + 3 + 1. Each emoji group is 3 and two groups
    # joined would be 8, so they stay apart.
    text = "\U0001f389" * 7
    assert len(text) == 7
    chunks = chunk_text(text, 3)
    assert chunks == ["\U0001f389" * 3, "\U0001f389" * 3, "\U0001f389"]


def test_accented_and_emoji_text_stays_within_limit_and_keeps_all_characters() -> None:
    text = "héllo wörld \U0001f389\U0001f389\U0001f389 naïve café"
    chunks = chunk_text(text, 5)
    assert all(len(chunk) <= 5 for chunk in chunks)
    assert all(chunk for chunk in chunks)
    assert _non_whitespace("".join(chunks)) == _non_whitespace(text)


# --- invariant: every chunk within the limit -------------------------------


_LONG_TOKEN = "z" * 97
_PROSE = (
    "The quick brown fox jumps over the lazy dog. Pack my box with five dozen "
    "liquor jugs.\n\nHow vexingly quick daft zebras jump!\nSphinx of black "
    "quartz, judge my vow.\n\n\n\nThe end."
)


@pytest.mark.parametrize(
    ("text", "limit"),
    [
        (_PROSE, 1),
        (_PROSE, 7),
        (_PROSE, 25),
        (_PROSE, 80),
        (_PROSE, 500),
        (_LONG_TOKEN, 10),
        (_LONG_TOKEN + "\n\n" + _LONG_TOKEN, 33),
        ("\U0001f389 naïve " * 20, 6),
        ("a\n\n" * 50, 3),
        ("word " * 200, 17),
    ],
    ids=[
        "prose-limit-1",
        "prose-limit-7",
        "prose-limit-25",
        "prose-limit-80",
        "prose-limit-500",
        "long-token-limit-10",
        "two-long-tokens-limit-33",
        "emoji-accent-limit-6",
        "blank-line-paragraphs-limit-3",
        "repeated-words-limit-17",
    ],
)
def test_every_chunk_is_at_most_limit_characters(text: str, limit: int) -> None:
    chunks = chunk_text(text, limit)
    assert chunks, "non-empty input must produce at least one chunk"
    for chunk in chunks:
        assert chunk, "no chunk may be empty"
        assert len(chunk) <= limit, f"chunk {chunk!r} is longer than {limit}"


# --- faithfulness: no text silently dropped --------------------------------


@pytest.mark.parametrize("limit", [5, 15, 30, 200])
def test_joined_chunks_reproduce_all_non_whitespace_text_in_order(limit: int) -> None:
    chunks = chunk_text(_PROSE, limit)
    assert _non_whitespace("\n\n".join(chunks)) == _non_whitespace(_PROSE)
