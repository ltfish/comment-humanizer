from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, OptionList, Static, TextArea
from textual.widgets.option_list import Option, OptionDoesNotExist

from .models import Status, TrackedComment
from .rewrite import EditError
from .session import Session

STATUS_MARK = {Status.PENDING: "·", Status.EDITED: "✎", Status.COMMITTED: "✓", Status.SKIPPED: "–"}
STATUS_STYLE = {Status.PENDING: "", Status.EDITED: "yellow", Status.COMMITTED: "green", Status.SKIPPED: "dim"}
FILTERS: list[Status | None] = [None, Status.PENDING, Status.EDITED, Status.COMMITTED, Status.SKIPPED]
CONTEXT_LINES = 4
DEFAULT_MESSAGE = "Humanize comments"


class CommentList(OptionList):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("enter", "select", "Edit"),
        Binding("r", "app.revert", "Revert"),
        Binding("x", "app.skip", "Skip"),
        Binding("f", "app.cycle_filter", "Filter"),
        Binding("c", "app.commit", "Commit"),
        Binding("q", "app.quit_app", "Quit"),
    ]


class Editor(TextArea):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "app.save", "Save"),
        Binding("escape", "app.cancel", "Cancel"),
    ]


class CommitScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, paths: list[str], message: str):
        super().__init__()
        self.paths = paths
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"Commit edits in {len(self.paths)} file(s):")
            yield Static(Text("\n".join(self.paths), style="dim"))
            yield Input(value=self.message, id="message")
            yield Label("enter: commit   esc: cancel", classes="hint")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "answer(True)", "Yes"),
        Binding("n,escape", "answer(False)", "No"),
    ]

    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.question)
            yield Label("y: yes   n: no", classes="hint")

    def action_answer(self, answer: bool) -> None:
        self.dismiss(answer)


class HumanizerApp(App[None]):
    TITLE = "comment-humanizer"
    CSS = """
    #list { width: 45%; border: round $primary; }
    #right { width: 55%; }
    #meta { height: auto; padding: 0 1; background: $boost; }
    #context { height: 1fr; border: round $secondary; }
    #editor { height: 1fr; border: round $accent; }
    CommitScreen, ConfirmScreen { align: center middle; }
    #dialog { width: 70; height: auto; padding: 1 2; border: thick $primary; background: $surface; }
    .hint { color: $text-muted; }
    """

    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.filter_idx = 0
        self.current: TrackedComment | None = None
        self.commit_message = DEFAULT_MESSAGE

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield CommentList(id="list")
            with Vertical(id="right"):
                yield Static(id="meta")
                with VerticalScroll(id="context"):
                    yield Static(id="context-text")
                yield Editor(id="editor", soft_wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"base {self.session.base[:12]}"
        self.refresh_list()
        self.query_one(CommentList).focus()
        if not self.session.items:
            self.notify("No added comments found.")

    # list

    def _visible(self) -> list[TrackedComment]:
        wanted = FILTERS[self.filter_idx]
        return [i for i in self.session.items if wanted is None or i.status is wanted]

    def _prompt(self, item: TrackedComment) -> Text:
        c = item.comment
        mark = "✗" if item.deleted else STATUS_MARK[item.status]
        text = Text(f"{mark} ", style=STATUS_STYLE[item.status], no_wrap=True, overflow="ellipsis")
        text.append(f"{c.start_line:>5} ", style="cyan")
        text.append(f"{c.kind.value:<9} ", style="magenta")
        text.append("(deleted)" if item.deleted else c.preview(), style="strike dim" if item.deleted else "")
        return text

    def refresh_list(self) -> None:
        lst = self.query_one(CommentList)
        keep = self.current.id if self.current else None
        options: list[Option] = []
        path = None
        for item in self._visible():
            if item.path != path:
                path = item.path
                options.append(Option(Text(path, style="bold"), disabled=True))
            options.append(Option(self._prompt(item), id=f"c{item.id}"))
        lst.set_options(options)
        wanted = FILTERS[self.filter_idx]
        lst.border_title = f"{len(self._visible())} comments" + (f" ({wanted.value})" if wanted else "")
        target = None
        if keep is not None:
            try:
                target = lst.get_option_index(f"c{keep}")
            except OptionDoesNotExist:
                target = None
        if target is None:
            target = next((i for i, o in enumerate(options) if not o.disabled), None)
        lst.highlighted = target
        if target is None:
            self.show(None)

    def _update_prompt(self, item: TrackedComment) -> None:
        lst = self.query_one(CommentList)
        try:
            lst.replace_option_prompt(f"c{item.id}", self._prompt(item))
        except OptionDoesNotExist:  # filtered out
            pass

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_id is not None:
            self.show(self.session.items[int(event.option_id[1:])])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self.current is not None and not self.current.deleted:
            self.query_one(Editor).focus()

    # right pane

    def show(self, item: TrackedComment | None) -> None:
        self.current = item
        meta = self.query_one("#meta", Static)
        context = self.query_one("#context-text", Static)
        editor = self.query_one(Editor)
        if item is None:
            meta.update("")
            context.update("")
            editor.load_text("")
            return
        c = item.comment
        status = "deleted" if item.deleted else item.status.value
        meta.update(
            Text.assemble(
                (f"{c.path}:{c.start_line}", "bold"),
                f"  {c.lang} {c.kind.value}  ",
                (f"[{status}]", STATUS_STYLE[item.status]),
            )
        )
        lines = self.session.files[c.path].split("\n")
        lo = max(1, item.region_start - CONTEXT_LINES)
        hi = min(len(lines), item.region_end + CONTEXT_LINES)
        text = Text()
        for n in range(lo, hi + 1):
            hot = not item.deleted and c.start_line <= n <= c.end_line
            text.append(f"{n:>5} ", style="dim")
            text.append(lines[n - 1].rstrip("\r") + "\n", style="bold yellow" if hot else "")
        context.update(text)
        editor.load_text("" if item.deleted else c.body)
        editor.read_only = item.deleted

    # actions

    def action_save(self) -> None:
        item = self.current
        if item is None:
            return
        try:
            self.session.save(item, self.query_one(Editor).text)
        except EditError as e:
            self.notify(str(e), severity="error")
            return
        self._after_change(item)
        self.query_one(CommentList).focus()

    def action_cancel(self) -> None:
        self.show(self.current)
        self.query_one(CommentList).focus()

    def action_revert(self) -> None:
        item = self.current
        if item is None:
            return
        try:
            self.session.revert(item)
        except EditError as e:
            self.notify(str(e), severity="error")
            return
        self._after_change(item)

    def action_skip(self) -> None:
        if self.current is not None:
            self.session.toggle_skip(self.current)
            self._after_change(self.current)

    def _after_change(self, item: TrackedComment) -> None:
        # line numbers of other comments in the file may have shifted; the list keeps its
        # membership until the filter changes, so the edited item does not vanish
        for other in self.session.items:
            if other.path == item.path:
                self._update_prompt(other)
        self.show(item)

    def action_cycle_filter(self) -> None:
        self.filter_idx = (self.filter_idx + 1) % len(FILTERS)
        self.refresh_list()

    def action_commit(self) -> None:
        paths = self.session.dirty_paths()
        if not paths:
            self.notify("Nothing to commit.")
            return

        def done(message: str | None) -> None:
            if message is None:
                return
            try:
                sha = self.session.commit(message)
            except EditError as e:
                self.notify(str(e), severity="error", timeout=10)
                return
            self.commit_message = message
            self.notify(f"Committed {sha}.")
            for item in self.session.items:
                self._update_prompt(item)
            self.show(self.current)

        self.push_screen(CommitScreen(paths, self.commit_message), done)

    def action_quit_app(self) -> None:
        paths = self.session.dirty_paths()
        if not paths:
            self.exit()
            return

        def done(yes: bool | None) -> None:
            if yes:
                self.exit()

        self.push_screen(ConfirmScreen(f"{len(paths)} file(s) have uncommitted edits. Quit anyway?"), done)
