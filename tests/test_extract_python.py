from comment_humanizer.extract import extract_python
from comment_humanizer.models import Kind


def kinds(src):
    return [(c.kind, c.start_line, c.end_line, c.body) for c in extract_python(src, "t.py")]


def test_line_comment_grouping():
    src = "# a\n# b\n\n# c\nx = 1\n    # d\n"
    assert kinds(src) == [
        (Kind.LINE, 1, 2, "a\nb"),
        (Kind.LINE, 4, 4, "c"),
        (Kind.LINE, 6, 6, "d"),
    ]


def test_indent_change_splits_group():
    src = "if x:\n    # a\n# b\n    pass\n"
    assert [(c.start_line, c.body) for c in extract_python(src, "t.py")] == [(2, "a"), (3, "b")]


def test_trailing_and_strings():
    src = 'x = "# no"  # yes\ny = f"{x} # no"\nz = """\n# no\n"""\n'
    (c,) = extract_python(src, "t.py")
    assert c.kind is Kind.TRAILING and c.body == "yes" and c.start_col == 12 and c.indent == ""


def test_blank_marker_lines_and_no_pad():
    src = "#tight\n#\n#more\n"
    (c,) = extract_python(src, "t.py")
    assert c.body == "tight\n\nmore" and c.pad is False


def test_pragmas_and_shebang_skipped():
    src = "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\nimport os  # noqa: F401\nx = 1  # type: ignore\n"
    assert extract_python(src, "t.py") == []


def test_docstrings():
    src = (
        '"""Module."""\n'
        "class C:\n"
        "    '''Class.'''\n"
        "    async def f(self):\n"
        '        """\n'
        "        Summary.\n"
        "\n"
        "            Detail.\n"
        '        """\n'
        "def g():\n"
        '    x = "not a docstring"\n'
    )
    docs = [c for c in extract_python(src, "t.py") if c.kind is Kind.DOCSTRING]
    assert [(c.start_line, c.end_line, c.body) for c in docs] == [
        (1, 1, "Module."),
        (3, 3, "Class."),
        (5, 9, "Summary.\n\n    Detail."),
    ]
    assert docs[2].delim is not None and docs[2].delim.leading_newline and docs[2].delim.closing_own_line


def test_docstring_prefix_and_unicode_columns():
    src = 'def f():\n    r"""Ünïcode \\d."""  # après\n'
    doc, trailing = extract_python(src, "t.py")
    assert doc.marker == 'r"""' and doc.body == "Ünïcode \\d." and doc.end_col == 22
    assert trailing.body == "après" and trailing.start_col == 24


def test_implicit_concatenation_skipped():
    src = 'def f():\n    """a""" """b"""\n'
    assert extract_python(src, "t.py") == []


def test_crlf():
    src = "# a\r\n# b\r\nx = 1  # c\r\n"
    assert kinds(src) == [(Kind.LINE, 1, 2, "a\nb"), (Kind.TRAILING, 3, 3, "c")]


def test_syntax_error_keeps_line_comments():
    src = "# ok\ndef (:\n"
    assert kinds(src) == [(Kind.LINE, 1, 1, "ok")]
