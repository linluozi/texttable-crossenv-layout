"""Reproduce the cross-environment bugs in texttable 1.7.2, then verify the fix.

Run with no arguments to exercise the *installed* texttable (i.e. whatever this
directory provides). Pass --root to point it at another copy instead:

    python reproduce.py                      # against this directory
    python reproduce.py --root /path/to/texttable-1.7.2

Because the defects only show up when the optional dependencies are missing, the
script can hide them for you:

    python reproduce.py --without wcwidth
    python reproduce.py --without wcwidth,cjkwrap

Exit code is 0 when every check passes, 1 otherwise.
"""

import argparse
import os
import sys
import tempfile
import unicodedata

CHECKS = []


def hide_modules(names):
    """Pretend these packages are not installed.

    Setting sys.modules[name] = None makes `import name` raise ImportError,
    which is exactly the code path the fallback branches guard.
    """
    for name in names:
        if name:
            sys.modules[name] = None


def check(name):
    def register(fn):
        CHECKS.append((name, fn))
        return fn
    return register


def display_width(text):
    """Independent reference: terminal columns occupied by ``text``."""
    total = 0
    for char in text:
        point = ord(char)
        category = unicodedata.category(char)
        if category in ("Mn", "Me", "Mc", "Cf", "Cc", "Zl", "Zp"):
            continue
        if category == "Lo" and (0x1160 <= point <= 0x11FF
                                 or 0xD7B0 <= point <= 0xD7FF):
            continue
        total += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return total


def rectangular(text):
    widths = [display_width(line) for line in text.split("\n") if line]
    return len(set(widths)) == 1, widths


def render(rows, max_width=0, widths=None):
    import texttable
    table = texttable.Texttable(max_width=max_width)
    table.set_cols_align(["l"] * len(rows[0]))
    if widths:
        table.set_cols_width(widths)
    table.add_rows(rows)
    return table.draw()


# ---------------------------------------------------------------------------
# Defect 1: zero-width characters are counted as one column
# ---------------------------------------------------------------------------

@check("D1a  CR at end of cell (CRLF file read with newline='')")
def d1a():
    rows = [["city", "pop"]]
    for city in ("北京", "上海", "广州"):
        rows.append([city + "\r", "1"])
    text = render(rows)
    ok, widths = rectangular(text)
    return ok, "line widths %r\n%s" % (widths, text)


@check("D1b  ZWJ / ZWNJ / ZWSP / BOM / VS16 are zero width")
def d1b():
    problems = []
    import texttable
    for char in ("\u200d", "\u200c", "\u200b", "\ufeff", "\ufe0f",
                 "\x00", "\x07", "\u2028"):
        got = texttable.uchar_width(char)
        if got != 0:
            problems.append("U+%04X reported %d, expected 0" % (ord(char), got))
    return not problems, "; ".join(problems) or "all zero width"


@check("D1c  same bytes, Windows vs POSIX read -> same table")
def d1c():
    payload = "北京\r\n上海\r\n广州\r\n".encode("utf-8")
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cities.txt")
    with open(path, "wb") as handle:
        handle.write(payload)
    with open(path, encoding="utf-8", newline="") as handle:
        keep_crlf = [line for line in handle.read().split("\n") if line]
    with open(path, encoding="utf-8") as handle:
        normalized = [line for line in handle.read().split("\n") if line]
    with open(path, "rb") as handle:
        binary = [line for line in handle.read().decode("utf-8").split("\n") if line]

    tables = {
        "windows(CRLF)": render([["c", "n"]] + [[c, "1"] for c in keep_crlf]),
        "posix(normalized)": render([["c", "n"]] + [[c, "1"] for c in normalized]),
        "binary+decode": render([["c", "n"]] + [[c, "1"] for c in binary]),
    }
    widths = {k: display_width(v.split("\n")[0]) for k, v in tables.items()}
    return len(set(tables.values())) == 1, "border widths %r" % widths


# ---------------------------------------------------------------------------
# Defect 2: combining marks that are also East Asian Wide
# ---------------------------------------------------------------------------

@check("D2a  combining + wide marks are zero width (U+3099, U+302A)")
def d2a():
    import texttable
    problems = []
    for char in ("\u3099", "\u309a", "\u302a"):
        got = texttable.uchar_width(char)
        if got != 0:
            problems.append("U+%04X reported %d, expected 0" % (ord(char), got))
    return not problems, "; ".join(problems) or "all zero width"


@check("D2b  Hangul medial vowels are zero width")
def d2b():
    import texttable
    problems = []
    for point in (0x1160, 0x1161, 0xD7B0, 0xD7CB):
        got = texttable.uchar_width(chr(point))
        if got != 0:
            problems.append("U+%04X reported %d, expected 0" % (point, got))
    return not problems, "; ".join(problems) or "all zero width"


# ---------------------------------------------------------------------------
# Defect 3: wrapping uses character counts instead of columns
# ---------------------------------------------------------------------------

@check("D3a  CJK cell wraps inside its column")
def d3a():
    problems = []
    for column_width in (2, 3, 4, 5, 6, 7, 8):
        try:
            text = render([["h"], ["中文字"]], widths=[column_width])
        except ValueError as exc:
            problems.append("width %d raised %s" % (column_width, exc))
            continue
        ok, widths = rectangular(text)
        if not ok:
            problems.append("width %d -> line widths %r" % (column_width, widths))
    return not problems, "; ".join(problems) or "all widths rectangular"


@check("D3b  CJK respects max_width")
def d3b():
    problems = []
    for max_width in (10, 12, 16, 20):
        text = render([["h"], ["一二三四五六七八九十"]], max_width=max_width)
        ok, widths = rectangular(text)
        if not ok:
            problems.append("max_width %d -> %r" % (max_width, widths))
        elif max(display_width(line) for line in text.split("\n")) > max_width:
            problems.append("max_width %d exceeded" % max_width)
    return not problems, "; ".join(problems) or "all within max_width"


@check("D3c  emoji respects max_width")
def d3c():
    problems = []
    for max_width in (12, 20):
        text = render([["h"], ["\U0001f600" * 8]], max_width=max_width)
        ok, widths = rectangular(text)
        if not ok:
            problems.append("max_width %d -> %r" % (max_width, widths))
    return not problems, "; ".join(problems) or "all rectangular"


@check("D3d  narrow column that cannot fit a wide character raises")
def d3d():
    try:
        import cjkwrap  # noqa: F401
        return True, "skipped: cjkwrap raises with its own message"
    except ImportError:
        pass
    try:
        render([["h"], ["中文字"]], widths=[1])
    except ValueError as exc:
        return True, "raised ValueError: %s" % exc
    return False, "no exception, broken table emitted"


@check("D4   plain ASCII output is unchanged")
def d4():
    expected = (
        "+----------+\n"
        "|    t     |\n"
        "+==========+\n"
        "| hello    |\n"
        "| world    |\n"
        "| foo bar  |\n"
        "| baz qux  |\n"
        "+----------+"
    )
    got = render([["t"], ["hello world foo bar baz qux"]], max_width=12)
    return got == expected, "identical" if got == expected else repr(got)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument(
        "--without", default="wcwidth",
        help="comma separated optional packages to hide (default: wcwidth, the "
             "branch where the defects live)")
    parser.add_argument(
        "--with", dest="keep", default="",
        help="comma separated packages to leave visible, undoing the default")
    args = parser.parse_args()

    hide = [n.strip() for n in args.without.split(",") if n.strip()]
    keep = [n.strip() for n in args.keep.split(",") if n.strip()]
    hide_modules([n for n in hide if n not in keep])
    sys.path.insert(0, args.root)

    import texttable
    import unicodedata as ud

    try:
        import wcwidth
        wc_version = wcwidth.__version__
    except ImportError:
        wc_version = "hidden" if "wcwidth" in sys.modules else "absent"

    print("texttable  : %s" % os.path.abspath(texttable.__file__))
    print("python     : %s" % sys.version.split()[0])
    print("unicodedata: %s" % ud.unidata_version)
    print("wcwidth    : %s" % wc_version)
    print()

    failed = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, "%s: %s" % (type(exc).__name__, exc)
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print("[%s] %s" % (status, name))
        if not ok:
            for line in str(detail).split("\n"):
                print("        " + line)

    print()
    print("%d/%d checks passed" % (len(CHECKS) - failed, len(CHECKS)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
