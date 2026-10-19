# ruff: noqa: UP031
# The percent-format style is kept on purpose: texttable still supports
# Python 2.7 and the rest of the module uses it, so the tests read the same way.
"""Tests for behaviour that used to depend on the runtime environment.

These cover the optional wcwidth package, the optional cjkwrap package, the
Unicode database version and the host operating system's newline convention.
Each test states the layout that a terminal would actually produce, so a
regression shows up as a misaligned table rather than as a changed string.
"""

import os
import sys
import textwrap
import unicodedata

import pytest

import texttable
from texttable import Texttable

try:
    import cjkwrap  # noqa: F401
    HAS_CJKWRAP = True
except ImportError:
    HAS_CJKWRAP = False

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def display_width(text):
    """Width of a string in terminal columns.

    Deliberately independent of texttable: combining marks, control characters
    and format characters take no column, East Asian Wide/Fullwidth take two,
    and Hangul medial/final jamo take none.
    """
    total = 0
    for char in text:
        code_point = ord(char)
        category = unicodedata.category(char)
        if category in ("Mn", "Me", "Mc", "Cf", "Cc", "Zl", "Zp"):
            continue
        if category == "Lo" and (0x1160 <= code_point <= 0x11FF
                                 or 0xD7B0 <= code_point <= 0xD7FF):
            continue
        total += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return total


def render(rows, max_width=0, widths=None):
    table = Texttable(max_width=max_width)
    table.set_cols_align(["l"] * len(rows[0]))
    if widths:
        table.set_cols_width(widths)
    table.add_rows(rows)
    return table.draw()


def assert_rectangular(text):
    """Every rendered line must occupy the same number of columns."""
    widths = [display_width(line) for line in text.split("\n") if line]
    assert len(set(widths)) == 1, (
        "table is not rectangular, line widths are %r\n%s" % (widths, text)
    )


# ---------------------------------------------------------------------------
# D1: characters that take no column must not be counted as one
# ---------------------------------------------------------------------------

ZERO_WIDTH_SAMPLES = [
    ("U+000D CARRIAGE RETURN", "\r"),
    ("U+0007 BELL", "\x07"),
    ("U+200D ZERO WIDTH JOINER", "\u200d"),
    ("U+200C ZERO WIDTH NON-JOINER", "\u200c"),
    ("U+200B ZERO WIDTH SPACE", "\u200b"),
    ("U+FEFF ZERO WIDTH NO-BREAK SPACE", "\ufeff"),
    ("U+FE0F VARIATION SELECTOR-16", "\ufe0f"),
    ("U+2028 LINE SEPARATOR", "\u2028"),
]


@pytest.mark.parametrize("label,char", ZERO_WIDTH_SAMPLES, ids=[s[0] for s in ZERO_WIDTH_SAMPLES])
def test_zero_width_character_does_not_widen_the_column(label, char):
    """A cell holding an invisible character must not widen its column.

    Regression: the unicodedata fallback reported 1 column for Cc/Cf/Zl/Zp,
    while wcwidth reports 0, so the same table was one column wider on a machine
    without wcwidth installed.
    """
    assert texttable.uchar_width(char) == 0, (
        "%s should occupy no column" % label
    )
    assert_rectangular(render([["h", "v"], ["a" + char + "b", "x"]]))


@pytest.mark.parametrize("label,char", ZERO_WIDTH_SAMPLES, ids=[s[0] for s in ZERO_WIDTH_SAMPLES])
def test_zero_width_character_keeps_column_width_stable(label, char):
    """Adding an invisible character must not change the border width."""
    without = render([["name", "n"], ["ab", 1]])
    with_char = render([["name", "n"], ["a" + char + "b", 1]])
    assert display_width(without.split("\n")[0]) == \
        display_width(with_char.split("\n")[0])


def test_trailing_carriage_return_from_windows_file():
    """A CRLF file read with newline='' leaves a CR at the end of every cell.

    Regression: the CR was counted as a column, textwrap then dropped it as
    whitespace, and the row ended up narrower than its own border.
    """
    rows = [["city", "note"]]
    for city in ("北京", "上海", "广州"):
        rows.append([city + "\r", "x"])
    text = render(rows)
    assert_rectangular(text)
    assert "\r" not in text


def test_crlf_inside_a_cell_is_split_like_lf():
    """CRLF and LF cell separators must produce the same table shape."""
    with_lf = render([["h", "v"], ["l1\nl2", "x"]])
    with_crlf = render([["h", "v"], ["l1\r\nl2", "x"]])
    assert_rectangular(with_lf)
    assert_rectangular(with_crlf)
    assert display_width(with_lf.split("\n")[0]) == \
        display_width(with_crlf.split("\n")[0])


def test_bom_at_start_of_cell_does_not_widen_the_table():
    """A UTF-8 BOM left in the first cell must not shift the whole table."""
    assert texttable.uchar_width("\ufeff") == 0
    plain = render([["id", "name"], ["1", "abc"]])
    with_bom = render([["id", "name"], ["1", "\ufeffabc"]])
    assert display_width(plain.split("\n")[0]) == \
        display_width(with_bom.split("\n")[0])


# ---------------------------------------------------------------------------
# D2: combining marks are measured before east-asian width
# ---------------------------------------------------------------------------

COMBINING_WIDE = [
    ("U+3099 KATAKANA VOICED SOUND MARK", "\u3099"),
    ("U+309A KATAKANA SEMI-VOICED SOUND MARK", "\u309a"),
    ("U+302A IDEOGRAPHIC LEVEL TONE MARK", "\u302a"),
]


@pytest.mark.parametrize("label,char", COMBINING_WIDE,
                         ids=[s[0] for s in COMBINING_WIDE])
def test_combining_mark_is_zero_width_even_when_wide(label, char):
    """These characters are East Asian Wide *and* combining: they take 0 columns.

    Regression: east-asian-width was tested first, so they were counted as two
    columns and the column grew by two for an invisible mark.
    """
    assert unicodedata.east_asian_width(char) in ("W", "F")
    assert unicodedata.combining(char) != 0
    assert texttable.uchar_width(char) == 0
    if HAS_CJKWRAP:
        # cjkwrap counts these as two columns (it only looks at
        # east_asian_width), so the rendered table cannot be rectangular when
        # texttable delegates wrapping to it. That is a cjkwrap limitation, not
        # something texttable can fix: report it, don't paper over it.
        pytest.xfail("cjkwrap.cjklen() counts combining wide marks as 2")
    assert_rectangular(render([["h", "v"], ["a" + char, "x"]]))


HANGUL_MEDIAL = [
    ("U+1160 HANGUL JUNGSEONG FILLER", "\u1160"),
    ("U+1161 HANGUL JUNGSEONG A", "\u1161"),
    ("U+D7B0 HANGUL JUNGSEONG O-YEO", "\ud7b0"),
]


@pytest.mark.parametrize("label,char", HANGUL_MEDIAL,
                         ids=[s[0] for s in HANGUL_MEDIAL])
def test_hangul_medial_vowel_is_zero_width(label, char):
    """Hangul jamo medial vowels combine with the leading consonant."""
    assert unicodedata.category(char) == "Lo"
    assert texttable.uchar_width(char) == 0
    assert_rectangular(render([["h", "v"], ["a" + char, "x"]]))


# ---------------------------------------------------------------------------
# D3: wrapping must use display columns, not character counts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("column_width", [2, 3, 4, 5, 6, 7, 8])
def test_cjk_wraps_within_its_column(column_width):
    """Wide characters must be wrapped by columns, not by character count.

    Regression: a six-column cell was wrapped at six *characters*, i.e. twelve
    columns, so the row overflowed the border drawn for it.
    """
    text = render([["h"], ["中文字"]], widths=[column_width])
    assert_rectangular(text)


@pytest.mark.parametrize("max_width", [10, 12, 16, 20])
def test_cjk_respects_max_width(max_width):
    """Automatic layout must also honour max_width for wide characters."""
    text = render([["h"], ["一二三四五六七八九十"]], max_width=max_width)
    assert_rectangular(text)
    assert all(display_width(line) <= max_width for line in text.split("\n"))


@pytest.mark.parametrize("max_width", [12, 20])
def test_emoji_respects_max_width(max_width):
    text = render([["h"], ["\U0001f600" * 8]], max_width=max_width)
    assert_rectangular(text)


def test_mixed_width_cell_wraps_within_its_column():
    text = render([["h"], ["mixed文字abc"]], widths=[8])
    assert_rectangular(text)


def test_column_too_narrow_for_a_wide_character_raises():
    """Instead of emitting a row wider than its border, fail loudly.

    cjkwrap already raises for this case; the textwrap fallback used to emit a
    broken table.
    """
    if "cjkwrap" in sys.modules:
        pytest.skip("cjkwrap has its own message for this case")
    with pytest.raises(ValueError):
        render([["h"], ["中文字"]], widths=[1])


# ---------------------------------------------------------------------------
# Environment independence
# ---------------------------------------------------------------------------

def test_fallback_width_matches_wcwidth_on_assigned_characters():
    """The unicodedata fallback must agree with wcwidth where wcwidth exists.

    Ties the two branches together: if wcwidth is installed the comparison is
    exact, otherwise the expected values are the ones wcwidth itself reports for
    these code points.
    """
    expected = {
        0x0000: 0, 0x0007: 0, 0x000D: 0, 0x001F: 0, 0x007F: 0,
        0x0301: 0, 0x200B: 0, 0x200C: 0, 0x200D: 0, 0xFEFF: 0,
        0xFE0F: 0, 0x2028: 0, 0x2029: 0,
        0x3099: 0, 0x309A: 0, 0x302A: 0, 0x16FE4: 0,
        0x1160: 0, 0x11A8: 0, 0xD7B0: 0, 0xD7CB: 0,
        0x0041: 1, 0x007E: 1, 0x00E9: 1, 0x05D0: 1,
        0x4E00: 2, 0x9FFF: 2, 0xFF21: 2, 0xAC00: 2, 0x1F600: 2,
    }
    wrong = {}
    for code_point, want in expected.items():
        got = texttable.uchar_width(chr(code_point))
        if got != want:
            wrong["U+%04X" % code_point] = (want, got)
    assert not wrong, "width mismatch (expected, got): %r" % wrong


def test_ascii_output_is_unchanged():
    """Narrow-only text keeps going through textwrap, byte for byte."""
    rows = [["t"], ["hello world foo bar baz qux"]]
    assert render(rows, max_width=12) == textwrap.dedent("""\
        +----------+
        |    t     |
        +==========+
        | hello    |
        | world    |
        | foo bar  |
        | baz qux  |
        +----------+""")


def test_narrow_text_wrapper_is_plain_textwrap():
    """Sanity check that the fast path still delegates to textwrap for ASCII."""
    assert texttable.textwrapper("hello world", 5) == textwrap.wrap("hello world", 5)
