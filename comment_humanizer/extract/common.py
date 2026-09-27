from __future__ import annotations

import os
import re

from ..models import DelimStyle

_STAR_LINE = re.compile(r"^(\s*)\*(?: |$)")


def split_lines(text: str) -> list[str]:
    """Split on "\\n" only (str.splitlines also splits on form feeds etc.), dropping "\\r"."""
    return [line.removesuffix("\r") for line in text.split("\n")]


def leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def parse_line_body(raw_bodies: list[str]) -> tuple[str, bool]:
    """Strip one space after the marker from each line; returns (body, pad)."""
    nonempty = [b for b in raw_bodies if b.strip()]
    pad = all(b.startswith(" ") for b in nonempty) if nonempty else True
    lines = [(b[1:] if pad and b.startswith(" ") else b).rstrip() for b in raw_bodies]
    return "\n".join(lines), pad


def parse_delimited(
    inner: str,
    open_: str,
    close: str,
    default_cont: str,
    default_close: str,
    star_ok: bool,
) -> tuple[str, DelimStyle]:
    segs = split_lines(inner)
    if len(segs) == 1:
        text = segs[0]
        style = DelimStyle(open_, close, text.startswith(" "), False, False, False, default_cont, default_close)
        return text.strip(), style

    first, last = segs[0], segs[-1]
    leading_newline = not first.strip()
    closing_own_line = not last.strip()
    cont = segs[1:-1] if closing_own_line else segs[1:]
    close_prefix = last if closing_own_line else default_close

    if leading_newline:
        pad = cont[-1].endswith(" ") if cont and not closing_own_line else True
    else:
        pad = first.startswith(" ")
    if not closing_own_line and cont:
        cont[-1] = cont[-1].rstrip()

    nonblank = [c for c in cont if c.strip()]
    if star_ok and nonblank and all(_STAR_LINE.match(c) or not c.strip() for c in cont):
        ws = os.path.commonprefix([_STAR_LINE.match(c).group(1) for c in nonblank])  # type: ignore[union-attr]
        cont_prefix = ws + "* "
        body_cont = [c.strip()[1:].removeprefix(" ").rstrip() if c.strip() else "" for c in cont]
    elif nonblank:
        cont_prefix = os.path.commonprefix([leading_ws(c) for c in nonblank])
        body_cont = [c[len(cont_prefix) :].rstrip() if c.strip() else "" for c in cont]
    else:
        cont_prefix = default_cont
        body_cont = ["" for _ in cont]

    lines = body_cont if leading_newline else [(first[1:] if pad else first).rstrip(), *body_cont]
    style = DelimStyle(open_, close, pad, leading_newline, closing_own_line, True, cont_prefix, close_prefix)
    return "\n".join(lines), style
