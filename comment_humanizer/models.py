from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    LINE = "line"  # one or more consecutive full-line `#` / `//` comments
    TRAILING = "trailing"  # line comment after code
    BLOCK = "block"  # Rust `/* */`
    DOCSTRING = "docstring"


class Status(Enum):
    PENDING = "pending"
    EDITED = "edited"
    COMMITTED = "committed"
    SKIPPED = "skipped"


@dataclass
class DelimStyle:
    """Layout of a delimited comment (Rust block comment or Python docstring)."""

    open: str  # e.g. "/**" or 'r"""'
    close: str  # e.g. "*/" or '"""'
    pad: bool  # a space separates the delimiters from the text on the same line
    leading_newline: bool  # text starts on the line after the opening delimiter
    closing_own_line: bool
    multiline: bool
    cont_prefix: str  # prefix of continuation lines, e.g. "    " or "   * "
    close_prefix: str  # prefix of the closing delimiter when it is on its own line


@dataclass
class Comment:
    path: str  # repo-relative, posix
    lang: str  # "python" | "rust"
    kind: Kind
    start_line: int  # 1-based, inclusive
    end_line: int
    start_col: int  # 0-based character column of the comment start on start_line
    end_col: int  # exclusive character column of the comment end on end_line
    indent: str  # leading whitespace of start_line
    marker: str  # "#", "//", "///", "//!" for line comments; opening delimiter otherwise
    body: str
    pad: bool = True  # line comments: a space follows the marker
    delim: DelimStyle | None = None

    def preview(self) -> str:
        for line in self.body.splitlines():
            if line.strip():
                return line.strip()
        return ""


@dataclass
class TrackedComment:
    """A comment selected for review, plus the editing state around it."""

    id: int
    comment: Comment
    original: Comment
    original_lines: list[str]
    # line range holding every modification made since startup; reverting replaces it
    region_start: int
    region_end: int
    status: Status = Status.PENDING
    deleted: bool = False
    dirty: bool = False  # saved since the last commit
    was_committed: bool = False

    @property
    def path(self) -> str:
        return self.comment.path
