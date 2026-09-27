import pytest

from comment_humanizer.vim import VimBuffer


def run(text, keys, row=0, col=0):
    v = VimBuffer(text)
    v.row, v.col = row, col
    actions = [v.feed(k) for k in (keys if isinstance(keys, list) else list(keys))]
    return v, actions


@pytest.mark.parametrize(
    "keys,pos",
    [
        ("l", (0, 1)),
        ("3l", (0, 3)),
        ("100l", (0, 13)),
        ("h", (0, 0)),
        ("w", (0, 4)),
        ("2w", (0, 7)),
        ("3w", (0, 9)),  # punctuation is its own word
        ("e", (0, 2)),
        ("2e", (0, 6)),
        ("$", (0, 13)),
        ("$0", (0, 0)),
        ("j", (1, 0)),
        ("G", (2, 2)),
        ("2G", (1, 2)),
        ("Ggg", (0, 0)),
        ("j$^", (1, 2)),
        ("4w", (1, 2)),
        ("4wb", (0, 9)),
    ],
)
def test_motions(keys, pos):
    v, _ = run("one two, three\n  second line\n  third", keys)
    assert (v.row, v.col) == pos


def test_w_stops_at_empty_line():
    v, _ = run("a\n\nb", "w")
    assert (v.row, v.col) == (1, 0)
    v, _ = run("a\n\nb", "ww")
    assert (v.row, v.col) == (2, 0)
    v, _ = run("a\n\nb", "b", row=2)
    assert (v.row, v.col) == (1, 0)


def test_j_clamps_column():
    v, _ = run("long line\nab", "$j")
    assert (v.row, v.col) == (1, 1)


@pytest.mark.parametrize(
    "keys,text,pos",
    [
        ("x", "ne two\nthree", (0, 0)),
        ("3x", " two\nthree", (0, 0)),
        ("dw", "two\nthree", (0, 0)),
        ("2dw", "\nthree", (0, 0)),  # dw stops at the end of the line
        ("de", " two\nthree", (0, 0)),
        ("wD", "one \nthree", (0, 3)),
        ("wd0", "two\nthree", (0, 0)),
        ("dd", "three", (0, 0)),
        ("2dd", "", (0, 0)),
        ("jdd", "one two", (0, 0)),
        ("dj", "", (0, 0)),
        ("ddu", "one two\nthree", (0, 0)),
        ("ddu\x12", "three", (0, 0)),
        ("yyp", "one two\none two\nthree", (1, 0)),
        ("yyP", "one two\none two\nthree", (0, 0)),
        ("ywP", "one one two\nthree", (0, 3)),
        ("xp", "noe two\nthree", (0, 1)),
        ("ddp", "three\none two", (1, 0)),
    ],
)
def test_edits(keys, text, pos):
    keys = ["ctrl+r" if k == "\x12" else k for k in keys]
    v, _ = run("one two\nthree", keys)
    assert (v.text, (v.row, v.col)) == (text, pos)


@pytest.mark.parametrize(
    "keys,text,pos",
    [
        ("i", "one two", (0, 0)),
        ("a", "one two", (0, 1)),
        ("A", "one two", (0, 7)),
        ("I", "one two", (0, 0)),
        ("o", "one two\n", (1, 0)),
        ("O", "\none two", (0, 0)),
        ("cw", " two", (0, 0)),
        ("wcw", "one ", (0, 4)),
        ("cc", "", (0, 0)),
        ("wC", "one ", (0, 4)),
    ],
)
def test_enter_insert(keys, text, pos):
    v, actions = run("one two", keys)
    assert actions[-1] == "insert"
    assert (v.text, (v.row, v.col)) == (text, pos)


def test_insert_undo_is_one_step():
    v, _ = run("one", "A")
    v.lines = ["one more"]  # typed in insert mode
    v.col = 8
    v.end_insert()
    assert v.col == 7
    v.feed("u")
    assert v.text == "one"


def test_noop_insert_leaves_no_undo_step():
    v, _ = run("one", "xi")
    v.end_insert()
    v.feed("u")
    assert v.text == "one"


def test_pending_and_special_keys():
    v, actions = run("a b", ["d", "escape", "escape"])
    assert v.text == "a b" and actions == [None, None, "leave"]
    v, actions = run("a b", [":"])
    assert actions == ["command"]
    v, _ = run("ab\ncd", ["delete", "enter", "l", "backspace"])
    assert v.text == "b\ncd" and (v.row, v.col) == (1, 0)
    v, _ = run("ab", ["d", "z", "x"])  # invalid operator motion resets
    assert v.text == "b"


def test_D_on_empty_line_keeps_line_break():
    v, _ = run("a\n\nb", "D", row=1)
    assert v.text == "a\n\nb"
