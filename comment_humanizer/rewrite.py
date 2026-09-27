from __future__ import annotations

from .extract.common import split_lines
from .models import Comment, DelimStyle, Kind


class EditError(Exception):
    pass


def normalize_body(body: str) -> list[str]:
    """Body text as lines; an empty list means "delete the comment"."""
    lines = [line.rstrip() for line in body.replace("\r\n", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    return lines


def _line_comment(c: Comment, text: str) -> str:
    if not text:
        return c.marker
    return c.marker + (" " if c.pad else "") + text


def render_delimited(style: DelimStyle, lines: list[str]) -> str:
    open_, close = style.open, style.close
    if not style.multiline and len(lines) == 1:
        pad = " " if style.pad and lines[0] else ""
        return open_ + pad + lines[0] + pad + close
    if not style.multiline and close in ('"', "'"):
        # a single-quoted docstring cannot span lines
        open_, close = open_ + close * 2, close * 3
    own_line = style.closing_own_line if style.multiline else True
    out = open_
    rest = lines
    if not style.leading_newline:
        out += (" " if style.pad and lines[0] else "") + lines[0]
        rest = lines[1:]
    for line in rest:
        out += "\n" + (style.cont_prefix + line if line else style.cont_prefix.rstrip())
    if own_line:
        out += "\n" + style.close_prefix + close
    else:
        out += (" " if style.pad else "") + close
    return out


def render(c: Comment, source: str, lines: list[str]) -> list[str]:
    """New source lines replacing lines c.start_line..c.end_line."""
    src = split_lines(source)
    head = src[c.start_line - 1][: c.start_col]
    tail = src[c.end_line - 1][c.end_col :]

    if c.kind in (Kind.LINE, Kind.TRAILING):
        if not lines:
            return [] if c.kind is Kind.LINE else [head.rstrip() + tail]
        rendered = [_line_comment(c, line) for line in lines]
        if c.kind is Kind.TRAILING and len(rendered) > 1:
            # a multi-line trailing comment moves above its code line
            return [c.indent + r for r in rendered] + [head.rstrip() + tail]
        out = [head + rendered[0], *(c.indent + r for r in rendered[1:])]
        out[-1] += tail
        return out

    if not lines:
        return _delete_delimited(c, head, tail)
    assert c.delim is not None
    return (head + render_delimited(c.delim, lines) + tail).split("\n")


def _delete_delimited(c: Comment, head: str, tail: str) -> list[str]:
    if not head.strip() and not tail.strip():
        return []  # the comment has its lines to itself
    if c.kind is Kind.DOCSTRING:
        raise EditError("the docstring shares its line with code; edit that line by hand")
    # an inline block comment: drop it and one space next to it
    if not head.strip():
        tail = tail.lstrip(" ")
    elif not tail.strip() or tail[0] in ",;)]}.":
        head = head.rstrip(" ")
    elif head.endswith(" ") and tail.startswith(" "):
        tail = tail[1:]
    return [head + tail]


def replace_lines(source: str, start: int, end: int, new_lines: list[str]) -> str:
    """Replace 1-based lines start..end (end == start - 1 inserts) with new_lines."""
    parts = source.split("\n")
    probe = parts[end - 1] if end >= start else parts[start - 1] if start - 1 < len(parts) else ""
    eol = "\r" if probe.endswith("\r") else ""
    parts[start - 1 : end] = [line + eol for line in new_lines]
    return "\n".join(parts)


def source_lines(source: str, start: int, end: int) -> list[str]:
    return split_lines(source)[start - 1 : end]
