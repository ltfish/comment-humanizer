import asyncio

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
