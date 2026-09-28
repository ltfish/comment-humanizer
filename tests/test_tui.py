import asyncio

from textual import events

from comment_humanizer.gitdiff import resolve_base
from comment_humanizer.models import Status
from comment_humanizer.session import Session
from comment_humanizer.tui import CommentList, CommitScreen, ConfirmScreen, Editor, HumanizerApp


def make_app(repo):
    repo.commit("base", **{"a.py": "x = 1\n"})
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("feat", **{"a.py": "# old one\nx = 1  # old two\n", "b.rs": "/// doc\nfn f() {}\n"})
    root = str(repo.root)
    return HumanizerApp(Session(root, resolve_base(root)))


def run(app, scenario):
    async def main():
        async with app.run_test(size=(120, 40)) as pilot:
            await scenario(app, pilot)

    asyncio.run(main())


def messages(app):
    return [n.message for n in app._notifications]


async def command(pilot, text):
    await pilot.press(":", *text, "enter")


def test_vim_edit_write_and_commit(repo):
    app = make_app(repo)

    async def scenario(app, pilot):
        lst = app.query_one(CommentList)
        editor = app.query_one(Editor)
        assert lst.option_count == 5  # two file headers + three comments
        assert app.current is app.session.items[0] and editor.text == "old one"

        await pilot.press("enter")
        assert editor.has_focus and editor.vim_mode == "normal"
        await pilot.press("c", "w")  # typed keys do not insert in normal mode
        assert editor.vim_mode == "insert" and editor.text == " one"
        await pilot.press(*"new", "escape")
        assert editor.vim_mode == "normal" and editor.text == "new one"
        await pilot.press("o", *"and more", "escape")

        await command(pilot, "w")
        assert repo.read("a.py") == "# new one\n# and more\nx = 1  # old two\n"
        assert editor.has_focus and editor.vim_mode == "normal"
        assert editor.cursor_location == (1, 7)
        assert "Saved a.py:1." in messages(app)
        await pilot.press("u")  # undo history survives :w
        assert editor.text == "new one"
        await command(pilot, "q!")
        assert lst.has_focus and editor.text == "new one\nand more"
        assert app.session.items[0].status is Status.EDITED

        # line numbers of the next comment are refreshed
        await pilot.press("j")
        assert app.current is app.session.items[1] and app.current.comment.start_line == 3

        await pilot.press("c")
        assert isinstance(app.screen, CommitScreen)
        await pilot.press("enter")
        assert not isinstance(app.screen, CommitScreen)
        assert repo.git("log", "-1", "--format=%s").strip() == "Humanize comments"
        assert app.session.items[0].status is Status.COMMITTED

    run(app, scenario)


def test_quit_commands_guard_unsaved_changes(repo):
    app = make_app(repo)

    async def scenario(app, pilot):
        editor = app.query_one(Editor)
        lst = app.query_one(CommentList)
        await pilot.press("enter", "x")
        assert editor.text == "ld one"
        await pilot.press("escape")  # normal-mode escape with unsaved changes stays
        assert editor.has_focus
        await command(pilot, "q")
        assert editor.has_focus and any("Unsaved" in m for m in messages(app))
        await command(pilot, "bogus")
        assert "Not an editor command: bogus" in messages(app)
        await command(pilot, "wq")
        assert lst.has_focus and repo.read("a.py").startswith("# ld one\n")

        await pilot.press("enter")
        await command(pilot, "w")
        assert "No changes." in messages(app)
        await command(pilot, "q")
        assert lst.has_focus
        await pilot.press("enter", "escape")
        assert lst.has_focus

    run(app, scenario)


def test_command_line_cancel_and_ctrl_s(repo):
    app = make_app(repo)

    async def scenario(app, pilot):
        editor = app.query_one(Editor)
        await pilot.press("enter", ":", "q")
        assert editor.vim_mode == "command" and editor.border_subtitle == ":q█"
        await pilot.press("escape")
        assert editor.vim_mode == "normal" and editor.has_focus
        await pilot.press(":", "backspace")  # deleting the colon leaves command mode
        assert editor.vim_mode == "normal"
        await pilot.press(":", "w", "backspace", "backspace", "x")
        assert editor.text == "ld one"

        await pilot.press("A", *"!", "ctrl+s")  # ctrl+s saves from insert mode too
        assert repo.read("a.py").startswith("# ld one!\n")
        app.query_one(CommentList).focus()
        await pilot.press("j", "enter", "A", *"?", "escape")
        app.query_one("#context").focus()  # ctrl+s works whatever has focus
        await pilot.press("ctrl+s")
        assert "x = 1  # old two?\n" in repo.read("a.py")

    run(app, scenario)


def test_skip_filter_revert(repo):
    app = make_app(repo)

    async def scenario(app, pilot):
        await pilot.press("x")
        assert app.session.items[0].status is Status.SKIPPED
        await pilot.press("f")  # pending only
        assert app.current is app.session.items[1]
        assert app.query_one(CommentList).option_count == 4

        await pilot.press("enter", "d", "w")
        await command(pilot, "wq")
        assert repo.read("a.py").endswith("x = 1  # two\n")
        await pilot.press("r")
        assert repo.read("a.py").endswith("# old two\n")

    run(app, scenario)


def test_error_is_reported_not_raised(repo):
    app = make_app(repo)

    async def scenario(app, pilot):
        await pilot.press("f", "f", "f")  # committed filter: empty list
        assert app.current is None
        await pilot.press("f", "f")  # back to all
        await pilot.press("j", "j")
        assert app.current is app.session.items[2]  # the Rust doc comment
        repo.write("b.rs", "changed\n")
        await pilot.press("enter", "x")
        await command(pilot, "w")
        assert app.session.items[2].status is Status.PENDING
        assert any("outside" in m for m in messages(app))

    run(app, scenario)


def test_delete_hotkey(repo):
    app = make_app(repo)

    async def scenario(app, pilot):
        lst = app.query_one(CommentList)
        await pilot.press("j", "d")
        assert repo.read("a.py") == "# old one\nx = 1\n"
        item = app.session.items[1]
        assert item.deleted and lst.has_focus
        assert "Deleted a.py:2." in messages(app)
        await pilot.press("d")
        assert "Already deleted; r restores it." in messages(app)
        await pilot.press("k", "d")  # deleting a line above shifts nothing it should not
        assert repo.read("a.py") == "x = 1\n"
        await pilot.press("r", "j", "r")
        assert repo.read("a.py") == "# old one\nx = 1  # old two\n"
        assert not any(i.deleted for i in app.session.items)

    run(app, scenario)


def test_visual_mode(repo):
    repo.commit("base", **{"a.py": "x = 1\n"})
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("feat", **{"a.py": "# one two three\n# four five\nx = 1\n"})
    root = str(repo.root)
    app = HumanizerApp(Session(root, resolve_base(root)))

    async def scenario(app, pilot):
        editor = app.query_one(Editor)
        await pilot.press("enter", "w", "v", "e")
        assert editor.vim_mode == "v" and editor.border_subtitle == "-- VISUAL --"
        assert editor.selected_text == "two"
        await pilot.press("right", "right")  # arrow keys extend the selection
        assert editor.selected_text == "two t"
        await pilot.press("o")
        assert editor.selection.end == (0, 4) and editor.selected_text == "two t"
        await pilot.press("escape")
        assert editor.vim_mode == "normal" and editor.selected_text == ""

        await pilot.press("V")
        assert editor.border_subtitle == "-- VISUAL LINE --" and editor.selected_text == "one two three"
        await pilot.press("j")
        assert editor.selected_text == "one two three\nfour five"
        await pilot.press("J")
        assert editor.text == "one two three four five" and editor.vim_mode == "normal"

        await pilot.press("w", "v", "e", "d")
        assert editor.text == "one two three  five" and editor.selected_text == ""  # J left the cursor at the join
        await pilot.press("v", "l", ":", "w", "enter")
        assert editor.vim_mode == "normal"
        assert repo.read("a.py") == "# one two three  five\nx = 1\n"

    run(app, scenario)


def test_replace_mode(repo):
    app = make_app(repo)

    async def scenario(app, pilot):
        editor = app.query_one(Editor)
        await pilot.press("enter", "R")
        assert editor.vim_mode == "replace" and editor.border_subtitle.startswith("-- REPLACE --")
        await pilot.press(*"NEW")
        assert editor.text == "NEW one" and editor.cursor_location == (0, 3)
        await pilot.press("backspace")
        assert editor.text == "NEd one"
        await pilot.press("right", "right", "right", *"12")  # arrows move; typing past the end appends
        assert editor.text == "NEd o12"
        await pilot.press("escape")
        assert editor.vim_mode == "normal" and editor.cursor_location == (0, 6)
        await pilot.press("0", "r", "n")
        assert editor.text == "nEd o12"
        await command(pilot, "w")
        assert repo.read("a.py").startswith("# nEd o12\n")

        await pilot.press("R", "Z", "ctrl+s")  # saving mid-session returns to normal mode
        assert editor.vim_mode == "normal" and repo.read("a.py").startswith("# ZEd o12\n")
        await pilot.press("x")
        assert editor.text == "Zd o12"  # the cursor stayed after the Z

        await pilot.press("0", "R")
        editor.post_message(events.Paste("ab\ncd"))  # pasting overwrites like typing
        await pilot.pause()
        assert editor.text == "ab\ncd12" and editor.vim_mode == "replace"

    run(app, scenario)


def test_quit_confirms_when_dirty(repo):
    app = make_app(repo)

    async def scenario(app, pilot):
        await pilot.press("enter", "x")
        await command(pilot, "wq")
        await pilot.press("q")
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("n")
        assert not isinstance(app.screen, ConfirmScreen)
        await pilot.press("q", "y")

    run(app, scenario)
    assert app.return_code == 0


def _preview_app(repo, comment_at):
    code = [f"x{i} = {i}  # " + "long " * 40 for i in range(200)]
    comment = [f"# comment line {i}" for i in range(20)]
    lines = code[:comment_at] + comment + code[comment_at:]
    repo.commit("base", **{"a.py": "\n".join(code) + "\n"})
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("feat", **{"a.py": "\n".join(lines) + "\n"})
    root = str(repo.root)
    return HumanizerApp(Session(root, resolve_base(root)))


def test_preview_fills_panel_and_centres_comment(repo):
    app = _preview_app(repo, 100)  # comment on lines 101-120 of 220

    async def main():
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            height = app.query_one("#context").scrollable_content_region.height
            lo, hi = app.context_range
            assert hi - lo + 1 == height > 20
            # long lines are clipped, not wrapped, so every line takes one row
            assert app.query_one("#context-text").size.height == height
            assert abs((101 - lo) - (hi - 120)) <= 1  # centred
            await pilot.resize_terminal(120, 70)
            await pilot.pause()
            taller = app.query_one("#context").scrollable_content_region.height
            lo, hi = app.context_range
            assert taller > height and hi - lo + 1 == taller
            assert abs((101 - lo) - (hi - 120)) <= 1

    asyncio.run(main())


def test_preview_near_file_start_still_fills_panel(repo):
    app = _preview_app(repo, 0)

    async def main():
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            height = app.query_one("#context").scrollable_content_region.height
            assert app.context_range == (1, height)

    asyncio.run(main())
