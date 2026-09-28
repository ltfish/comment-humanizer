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


# visual mode

TEXT = "one two three\n  four five\nsix"


def vis(keys, row=0, col=0, text=TEXT):
    v, actions = run(text, keys, row, col)
    return v, actions


def test_visual_enter_switch_and_leave():
    v, _ = vis("v")
    assert v.visual == "v" and v.anchor == (0, 0)
    v, _ = vis("vV")
    assert v.visual == "V"
    v, _ = vis("vv")
    assert v.visual is None
    v, _ = vis(["v", "l", "escape"])
    assert v.visual is None and (v.row, v.col) == (0, 1) and v.text == TEXT


@pytest.mark.parametrize(
    "keys,sel",
    [
        ("vw", ((0, 0), (0, 4))),
        ("v2e", ((0, 0), (0, 6))),
        ("v$", ((0, 0), (0, 13))),  # past the last character: takes the line break
        ("vj", ((0, 0), (1, 0))),
        ("vG", ((0, 0), (2, 0))),
        ("v3l", ((0, 0), (0, 3))),
        ("wvb", ((0, 0), (0, 4))),  # selection is ordered whatever the direction
        ("vwo", ((0, 0), (0, 4))),
    ],
)
def test_visual_motions(keys, sel):
    v, _ = vis(keys)
    assert v.selection() == sel


def test_visual_o_moves_cursor_to_other_end():
    v, _ = vis("vwo")
    assert (v.row, v.col) == (0, 0) and v.anchor == (0, 4)


@pytest.mark.parametrize(
    "keys,text,pos",
    [
        ("vld", "e two three\n  four five\nsix", (0, 0)),
        ("vex", " two three\n  four five\nsix", (0, 0)),
        ("wvjd", "one r five\nsix", (0, 4)),
        ("Vd", "  four five\nsix", (0, 2)),
        ("Vjd", "six", (0, 0)),
        ("jVkx", "six", (0, 0)),
        ("v$d", "  four five\nsix", (0, 0)),  # $ in visual takes the line break too
        ("veyP", "oneone two three\n  four five\nsix", (0, 2)),
        ("vey$vp", "one two threone\n  four five\nsix", (0, 14)),
        ("Vy2jp", "one two three\n  four five\nsix\none two three", (3, 0)),
        ("veyjVp", "one two three\none\nsix", (1, 0)),
        ("VyjvlP", "one two three\n\none two three\nfour five\nsix", (2, 0)),
        ("v2e~", "ONE TWO three\n  four five\nsix", (0, 0)),
        ("VjU", "ONE TWO THREE\n  FOUR FIVE\nsix", (0, 0)),
        ("VUVu", TEXT, (0, 0)),
        ("VJ", "one two three four five\nsix", (0, 13)),
        ("VjjJ", "one two three four five six", (0, 23)),
    ],
)
def test_visual_ops(keys, text, pos):
    v, _ = vis(keys)
    assert (v.text, (v.row, v.col), v.visual) == (text, pos, None)


@pytest.mark.parametrize("keys,text", [("vec", " two three"), ("ves", " two three"), ("Vc", "")])
def test_visual_change_enters_insert(keys, text):
    v, actions = vis(keys)
    assert actions[-1] == "insert" and v.lines[0] == text and v.visual is None


def test_visual_yank_keeps_text_and_register_shape():
    v, _ = vis("wvey")
    assert v.text == TEXT and v.register == ("two", False) and (v.row, v.col) == (0, 4)
    v, _ = vis("Vjy")
    assert v.register == ("one two three\n  four five", True)


def test_visual_ops_are_one_undo_step():
    for keys in ("vjd", "VjU", "VjJ", "veyjVp"):
        v, _ = vis(keys + "u")
        assert v.text == TEXT, keys
    v, _ = vis("VUu")
    v.feed("ctrl+r")
    assert v.lines[0] == "ONE TWO THREE"


def test_visual_colon_opens_command_line():
    v, actions = vis("vl:")
    assert actions[-1] == "command" and v.visual is None


def test_visual_on_empty_line_takes_line_break():
    v, _ = vis("vd", row=1, text="a\n\nb")
    assert v.text == "a\nb"


def test_visual_P_keeps_register_and_p_swaps_it():
    v, _ = vis("veywvep")
    assert v.lines[0] == "one one three" and v.register == ("two", False)
    v, _ = vis("veywveP")
    assert v.lines[0] == "one one three" and v.register == ("one", False)


def test_visual_dollar_display_column_and_reset():
    v, _ = vis("v$")
    assert v.col == 13 and v.eol
    v, _ = vis("v$h")
    assert v.col == 12 and not v.eol


# replace mode


def rep_run(keys, text="abc def\nxyz", row=0, col=0):
    return run(text, keys, row, col)


def test_R_overwrites_and_appends():
    v, _ = rep_run(["R", "X", "Y"])
    assert v.replacing and v.text == "XYc def\nxyz" and v.col == 2
    v, _ = rep_run(["$", "R", "1", "2", "3"])
    assert v.lines[0] == "abc de123" and v.col == 9  # past the end: appends


def test_R_escape_steps_back_and_is_one_undo_step():
    v, _ = rep_run(["R", "X", "Y", "escape"])
    assert not v.replacing and v.col == 1
    v.feed("u")
    assert v.text == "abc def\nxyz"
    v, _ = rep_run(["R", "escape"])
    assert v.undo_stack == []  # a session that changed nothing leaves no undo step


def test_R_enter_splits_line():
    v, _ = rep_run(["l", "R", "enter", "Q"])
    assert v.text == "a\nQc def\nxyz" and (v.row, v.col) == (1, 1)


def test_R_backspace_restores_and_only_moves_outside_session():
    v, _ = rep_run(["$", "R", "1", "2", "3", "backspace", "backspace", "backspace", "backspace"])
    # 1 overwrote f; 2 and 3 were appended; the fourth backspace only moves left
    assert v.lines[0] == "abc def" and v.col == 5
    v, _ = rep_run(["l", "R", "enter", "Q", "backspace", "backspace"])
    assert v.text == "abc def\nxyz" and (v.row, v.col) == (0, 1)


def test_R_arrows_move_and_forget_restores():
    v, _ = rep_run(["R", "X", "right", "Y", "backspace", "backspace"])
    assert v.lines[0] == "Xbc def" and v.col == 1  # Y restored to c; X kept after the move
    v, _ = rep_run(["R", "down", "Z"])
    assert v.text == "abc def\nZyz"


@pytest.mark.parametrize(
    "keys,text,pos",
    [
        (["r", "X"], "Xbc def\nxyz", (0, 0)),
        (["3", "r", "-"], "--- def\nxyz", (0, 2)),
        (["$", "2", "r", "-"], "abc def\nxyz", (0, 6)),  # too few characters: no-op
        (["l", "r", "enter"], "a\nc def\nxyz", (1, 0)),
        (["r", "escape", "x"], "bc def\nxyz", (0, 0)),  # escape cancels a pending r
        (["v", "e", "r", "*"], "*** def\nxyz", (0, 0)),
        (["v", "j", "r", "."], ".......\n.yz", (0, 0)),  # line breaks survive
        (["V", "r", "#"], "#######\nxyz", (0, 0)),
        (["v", "r", "enter", "x"], "bc def\nxyz", (0, 0)),  # visual r<enter> is not supported: cancels r
    ],
)
def test_r_replaces_characters(keys, text, pos):
    v, _ = rep_run(keys)
    assert (v.text, (v.row, v.col)) == (text, pos)
    assert not v.replacing and v.visual is None


def test_r_is_one_undo_step():
    v, _ = rep_run(["3", "r", "-", "u"])
    assert v.text == "abc def\nxyz"
    v, _ = rep_run(["v", "e", "r", "*", "u"])
    assert v.text == "abc def\nxyz"
