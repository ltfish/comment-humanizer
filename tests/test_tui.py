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


def test_edit_save_commit(repo):
    app = make_app(repo)

    async def scenario(app, pilot):
        lst = app.query_one(CommentList)
        editor = app.query_one(Editor)
        assert lst.option_count == 5  # two file headers + three comments
        assert app.current is app.session.items[0] and editor.text == "old one"

        await pilot.press("enter")
        assert editor.has_focus
        editor.load_text("new one\nand more")
        await pilot.press("ctrl+s")
        assert lst.has_focus
        assert repo.read("a.py") == "# new one\n# and more\nx = 1  # old two\n"
        assert app.session.items[0].status is Status.EDITED

        # line numbers of the next comment are refreshed in the list
        await pilot.press("j")
        assert app.current is app.session.items[1] and app.current.comment.start_line == 3

        await pilot.press("c")
        assert isinstance(app.screen, CommitScreen)
        await pilot.press("enter")
        assert not isinstance(app.screen, CommitScreen)
        assert repo.git("log", "-1", "--format=%s").strip() == "Humanize comments"
        assert app.session.items[0].status is Status.COMMITTED

    run(app, scenario)


def test_cancel_skip_filter_revert(repo):
    app = make_app(repo)

    async def scenario(app, pilot):
        editor = app.query_one(Editor)
        await pilot.press("enter")
        editor.load_text("discarded")
        await pilot.press("escape")
        assert editor.text == "old one" and repo.read("a.py").startswith("# old one")

        await pilot.press("x")
        assert app.session.items[0].status is Status.SKIPPED
        await pilot.press("f")  # pending only
        assert app.current is app.session.items[1]
        assert app.query_one(CommentList).option_count == 4

        await pilot.press("enter")
        editor.load_text("bad */ text")
        await pilot.press("ctrl+s")  # fine for Python: `*/` is ordinary text
        assert repo.read("a.py").endswith("# bad */ text\n")
        await pilot.press("r")
        assert repo.read("a.py").endswith("# old two\n")

    run(app, scenario)


def test_error_is_reported_not_raised(repo):
    app = make_app(repo)

    async def scenario(app, pilot):
        await pilot.press("f", "f", "f")  # committed filter: empty list
        assert app.current is None
        await pilot.press("f", "f")  # back to all
        for _ in range(2):
            await pilot.press("j")
        assert app.current is app.session.items[2]  # the Rust doc comment
        repo.write("b.rs", "changed\n")
        await pilot.press("enter")
        app.query_one(Editor).load_text("new")
        await pilot.press("ctrl+s")
        assert app.session.items[2].status is Status.PENDING
        assert any("outside" in n.message for n in app._notifications)

    run(app, scenario)


def test_quit_confirms_when_dirty(repo):
    app = make_app(repo)

    async def scenario(app, pilot):
        await pilot.press("enter")
        app.query_one(Editor).load_text("dirty")
        await pilot.press("ctrl+s", "q")
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("n")
        assert not isinstance(app.screen, ConfirmScreen)
        await pilot.press("q", "y")

    run(app, scenario)
    assert app.return_code == 0
