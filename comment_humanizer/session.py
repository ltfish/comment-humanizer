from __future__ import annotations

import ast
import difflib
import os

from . import gitdiff
from .extract import extract
from .gitdiff import GitError, git
from .models import Comment, Kind, Status, TrackedComment
from .rewrite import EditError, normalize_body, render, replace_lines, source_lines


def _keep_ends(text: str) -> list[str]:
    parts = text.split("\n")
    out = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out


def make_patch(path: str, old: str, new: str) -> str:
    out: list[str] = []
    for line in difflib.unified_diff(_keep_ends(old), _keep_ends(new), f"a/{path}", f"b/{path}", n=3):
        out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(out)


def _parses(lang: str, text: str) -> bool:
    if lang != "python":
        return True
    try:
        ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    return True


class Session:
    """Comments under review and the edits made to them; knows nothing about the UI."""

    def __init__(
        self,
        repo: str,
        base: str,
        pathspecs: list[str] | None = None,
        author: str | None = None,
        no_verify: bool = False,
    ):
        self.repo = repo
        self.base = base
        self.author = author
        self.no_verify = no_verify
        self.files: dict[str, str] = {}  # contents as last written by us
        self.baseline: dict[str, str] = {}  # contents as of startup or the last commit
        self.comments: dict[str, list[Comment]] = {}  # every comment per file, current positions
        self.items: list[TrackedComment] = []

        for path, added in sorted(gitdiff.added_lines(repo, base, pathspecs).items()):
            try:
                text = self._read(path)
            except (OSError, UnicodeDecodeError):
                continue
            all_comments = extract(text, path)
            self.files[path] = self.baseline[path] = text
            self.comments[path] = all_comments
            for c in all_comments:
                if any(line in added for line in range(c.start_line, c.end_line + 1)):
                    orig = source_lines(text, c.start_line, c.end_line)
                    self.items.append(TrackedComment(len(self.items), c, c, orig, c.start_line, c.end_line))

    def _read(self, path: str) -> str:
        with open(os.path.join(self.repo, path), encoding="utf-8", newline="") as f:
            return f.read()

    def _write(self, path: str, text: str) -> None:
        with open(os.path.join(self.repo, path), "w", encoding="utf-8", newline="") as f:
            f.write(text)
        self.files[path] = text

    def current_text(self, path: str) -> str:
        text = self._read(path)
        if text != self.files[path]:
            raise EditError(f"{path} was modified outside comment-humanizer; restart to pick up the changes")
        return text

    def _locate(self, comments: list[Comment], line: int, col: int) -> Comment | None:
        on_line = [c for c in comments if c.start_line == line]
        for c in on_line:
            if c.start_col == col:
                return c
        return on_line[0] if on_line else None

    def _apply(
        self, item: TrackedComment, start: int, end: int, new_lines: list[str], expect: str | None, expect_col: int
    ) -> None:
        """Replace lines start..end of the item's file, validate, then re-anchor every tracked comment."""
        path = item.path
        old_text = self.current_text(path)
        new_text = replace_lines(old_text, start, end, new_lines)
        lang = item.comment.lang
        if _parses(lang, old_text) and not _parses(lang, new_text):
            raise EditError("the edit would break the file's syntax")

        old_comments = self.comments[path]
        new_comments = extract(new_text, path)
        found: Comment | None = None
        if expect is not None:
            found = self._locate(new_comments, start, expect_col)
            if found is None or found.body != expect:
                raise EditError(
                    "the new text does not read back as the same comment "
                    "(a stray delimiter or quote, or it merges with an adjacent comment)"
                )
        was_present = not item.deleted
        expected_count = len(old_comments) - int(was_present) + int(found is not None)
        if len(new_comments) != expected_count:
            raise EditError("the edit changes the surrounding comments (merges with an adjacent comment?)")

        delta = len(new_lines) - (end - start + 1)
        for other in self.items:
            if other.path != path or other is item:
                continue
            if other.region_start > end:
                other.region_start += delta
                other.region_end += delta
            if other.deleted:
                continue
            c = other.comment
            same_line = [x for x in old_comments if x.start_line == c.start_line]
            ordinal = next((i for i, x in enumerate(same_line) if x is c), 0)
            line = c.start_line + delta if c.start_line > end else c.start_line
            candidates = [x for x in new_comments if x.start_line == line]
            if ordinal < len(candidates):
                other.comment = candidates[ordinal]
            else:
                other.deleted = True

        self._write(path, new_text)
        self.comments[path] = new_comments
        item.region_end += delta
        if found is None:
            item.deleted = True
        else:
            item.comment = found
            item.deleted = False

    def save(self, item: TrackedComment, body: str) -> None:
        if item.deleted:
            raise EditError("the comment was deleted; revert it first")
        c = item.comment
        lines = normalize_body(body)
        if lines == normalize_body(c.body):
            return
        text = self.current_text(item.path)
        new_lines = render(c, text, lines)
        moved_above = c.kind is Kind.TRAILING and len(lines) > 1
        expect_col = len(c.indent) if moved_above else c.start_col
        try:
            self._apply(item, c.start_line, c.end_line, new_lines, "\n".join(lines) if lines else None, expect_col)
        except EditError as e:
            if moved_above and "adjacent" in str(e):
                raise EditError(
                    "a multi-line trailing comment moves above its line, where it would merge with the comment "
                    "already there; keep it to one line or edit that comment instead"
                ) from e
            raise
        item.status = Status.EDITED
        item.dirty = True

    def revert(self, item: TrackedComment) -> None:
        text = self.current_text(item.path)
        if source_lines(text, item.region_start, item.region_end) == item.original_lines and not item.deleted:
            return
        self._apply(
            item, item.region_start, item.region_end, item.original_lines, item.original.body, item.original.start_col
        )
        if item.was_committed:
            item.status, item.dirty = Status.EDITED, True
        else:
            item.status, item.dirty = Status.PENDING, False

    def toggle_skip(self, item: TrackedComment) -> None:
        if item.status is Status.PENDING:
            item.status = Status.SKIPPED
        elif item.status is Status.SKIPPED:
            item.status = Status.PENDING

    def dirty_paths(self) -> list[str]:
        return [p for p in sorted(self.files) if self.files[p] != self.baseline[p]]

    def commit(self, message: str) -> str:
        """Commit only the edits made here, leaving other staged or unstaged work alone."""
        paths = self.dirty_paths()
        if not paths:
            raise EditError("nothing to commit")
        if not message.strip():
            raise EditError("empty commit message")
        for p in paths:
            self.current_text(p)
        staged = git(self.repo, "diff", "--cached", "--name-only", "--", *paths).split()
        if staged:
            raise EditError(f"unstage or commit the staged changes in {', '.join(staged)} first")

        patch = "".join(make_patch(p, self.baseline[p], self.files[p]) for p in paths)
        index = git(self.repo, "rev-parse", "--path-format=absolute", "--git-path", "index.comment-humanizer").strip()
        env = {"GIT_INDEX_FILE": index}
        args = ["commit", "-q", "-m", message]
        if self.author:
            args.append(f"--author={self.author}")
        if self.no_verify:
            args.append("--no-verify")
        try:
            git(self.repo, "read-tree", "HEAD", env=env)
            try:
                git(self.repo, "apply", "--cached", "-", stdin=patch, env=env)
            except GitError as e:
                raise EditError(f"the edits do not apply to HEAD (uncommitted changes nearby?): {e}") from e
            git(self.repo, *args, env=env)
        except GitError as e:
            raise EditError(str(e)) from e
        finally:
            if os.path.exists(index):
                os.unlink(index)
        # the real index still holds the old HEAD version of these files
        git(self.repo, "reset", "-q", "HEAD", "--", *paths)

        for p in paths:
            self.baseline[p] = self.files[p]
        for item in self.items:
            if item.dirty and item.path in paths:
                item.dirty = False
                item.was_committed = True
                item.status = Status.COMMITTED
        return git(self.repo, "rev-parse", "--short", "HEAD").strip()
