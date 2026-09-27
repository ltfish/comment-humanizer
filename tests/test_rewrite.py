import pytest

from comment_humanizer.extract import extract
from comment_humanizer.rewrite import EditError, normalize_body, render, replace_lines

PY = '''"""Module."""
import os


# first
#
# second
Y = 1


def f(x):  # trailing
    """
    Summary.

        Indented.
    """
    return x


class C:
    \'\'\'Single.\'\'\'

    def g(self):
        """Starts here,
        ends here."""
'''

RS = """//! Crate.
/// Doc a.
/// Doc b.
fn f() { // trailing
    /* one */
    /**
     * Star.
     *
     * More.
     */
    /* plain
       continued */
}
"""


def edit(src, path, index, body):
    c = extract(src, path)[index]
    return replace_lines(src, c.start_line, c.end_line, render(c, src, normalize_body(body)))


@pytest.mark.parametrize("src,path", [(PY, "t.py"), (RS, "t.rs"), (PY.replace("\n", "\r\n"), "t.py")])
def test_unchanged_body_round_trips(src, path):
    for i, c in enumerate(extract(src, path)):
        assert edit(src, path, i, c.body) == src, c


@pytest.mark.parametrize("src,path", [(PY, "t.py"), (RS, "t.rs")])
def test_edits_extract_back(src, path):
    for i, c in enumerate(extract(src, path)):
        new_body = "Rewritten.\n\nSecond paragraph."
        new_src = edit(src, path, i, new_body)
        again = [x for x in extract(new_src, path) if x.start_line == c.start_line]
        assert again[0].body == new_body, c


def test_line_comment_grows():
    assert edit("    # old\nx\n", "t.py", 0, "one\ntwo") == "    # one\n    # two\nx\n"


def test_trailing_grows_moves_above():
    src = "if y:\n    x = 1  # old\n"
    assert edit(src, "t.py", 0, "one\ntwo") == "if y:\n    # one\n    # two\n    x = 1\n"


def test_rust_trailing_single_line():
    assert edit("let a = 1; // old\n", "t.rs", 0, "new") == "let a = 1; // new\n"


def test_delete_line_comment_and_trailing():
    assert edit("# a\n# b\nx = 1\n", "t.py", 0, "") == "x = 1\n"
    assert edit("x = 1  # a\n", "t.py", 0, "  \n") == "x = 1\n"


@pytest.mark.parametrize(
    "src,path,expected",
    [
        ('def f():\n    """Doc.\n\n    More.\n    """\n    return 1\n', "t.py", "def f():\n    return 1\n"),
        ("fn f() {\n    /*\n     * a\n     */\n    g();\n}\n", "t.rs", "fn f() {\n    g();\n}\n"),
        ("    /* a */ g();\n", "t.rs", "    g();\n"),
        ("g(); /* a */\n", "t.rs", "g();\n"),
        ("g(1, /* a */ 2);\n", "t.rs", "g(1, 2);\n"),
        ("g(/* a */);\n", "t.rs", "g();\n"),
        ("g(1 /* a\n  b */, 2);\n", "t.rs", "g(1, 2);\n"),
    ],
)
def test_delete_delimited(src, path, expected):
    assert edit(src, path, 0, "") == expected


def test_delete_docstring_sharing_a_line_rejected():
    with pytest.raises(EditError, match="shares its line"):
        edit('def f(): """Doc."""\n', "t.py", 0, "")


def test_single_line_docstring_grows():
    src = "def f():\n    '''Doc.'''\n"
    assert edit(src, "t.py", 0, "Doc.\n\nMore.") == "def f():\n    '''''Doc.\n\n    More.\n    '''''\n".replace(
        "'''''", "'''"
    )


def test_single_quoted_docstring_upgrades_to_triple():
    src = "def f():\n    'Doc.'\n"
    assert edit(src, "t.py", 0, "a\nb") == "def f():\n    '''a\n    b\n    '''\n"


def test_star_block_grows_from_single_line():
    src = "    /* one */\n"
    assert edit(src, "t.rs", 0, "one\ntwo") == "    /* one\n     * two\n     */\n"


def test_star_block_keeps_layout():
    src = "/**\n * A.\n */\n"
    assert edit(src, "t.rs", 0, "B.\n\nC.") == "/**\n * B.\n *\n * C.\n */\n"


def test_no_trailing_newline():
    assert edit("x = 1  # a", "t.py", 0, "b") == "x = 1  # b"


def test_normalize_body():
    assert normalize_body("\n a  \r\nb\n\n") == ["", " a", "b", "", ""]
    assert normalize_body(" \n") == []


@pytest.mark.parametrize(
    "src,path,body,expected",
    [
        ("# a\nx = 1\n", "t.py", "\na\n", "#\n# a\n#\nx = 1\n"),
        ("x = 1  # a\n", "t.py", "a\n", "# a\n#\nx = 1\n"),
        ("/// a\nfn f() {}\n", "t.rs", "a\n\n", "/// a\n///\n///\nfn f() {}\n"),
        ('def f():\n    """A."""\n', "t.py", "A.\n", 'def f():\n    """A.\n\n    """\n'),
        ('def f():\n    """\n    A.\n    """\n', "t.py", "\nA.\n", 'def f():\n    """\n\n    A.\n\n    """\n'),
        ("/**\n * a\n */\n", "t.rs", "\na\n", "/**\n *\n * a\n *\n */\n"),
    ],
)
def test_blank_edge_lines_are_kept(src, path, body, expected):
    out = edit(src, path, 0, body)
    assert out == expected
    assert extract(out, path)[0].body == body


def test_blank_edge_lines_round_trip_unchanged():
    for src, path in [
        ("#\n# a\n#\nx\n", "t.py"),
        ('def f():\n    """\n\n    A.\n\n    """\n', "t.py"),
        ("/*\n\n   a\n\n*/\n", "t.rs"),
    ]:
        c = extract(src, path)[0]
        assert c.body.startswith("\n") or c.body.endswith("\n")
        assert edit(src, path, 0, c.body) == src
