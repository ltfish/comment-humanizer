from __future__ import annotations

import bisect

from ..models import Comment, Kind
from .common import leading_ws, parse_delimited, parse_line_body, split_lines


def _skip_quoted(src: str, i: int) -> int:
    """`i` points just past an opening double quote; returns the index past the closing one."""
    n = len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
        elif c == '"':
            return i + 1
        else:
            i += 1
    return n


def _lex(src: str) -> list[tuple[str, int, int]]:
    """Return ("line" | "block", start, end) spans of comments, skipping string and char literals."""
    spans: list[tuple[str, int, int]] = []
    n = len(src)
    i = 0
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            spans.append(("line", i, j))
            i = j
        elif c == "/" and nxt == "*":
            depth, j = 1, i + 2
            while j < n and depth:
                if src.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif src.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            if depth:
                break  # unterminated
            spans.append(("block", i, j))
            i = j
        elif c == '"':
            i = _skip_quoted(src, i + 1)
        elif c == "'":
            if nxt == "\\":
                j = src.find("'", i + 3)
                i = n if j == -1 else j + 1
            elif i + 2 < n and src[i + 2] == "'":
                i += 3
            else:
                i += 1  # lifetime or label
        elif c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            following = src[j] if j < n else ""
            if word in ("r", "br", "cr") and following in ('"', "#"):
                k = j
                while k < n and src[k] == "#":
                    k += 1
                if k < n and src[k] == '"':
                    terminator = '"' + "#" * (k - j)
                    e = src.find(terminator, k + 1)
                    i = n if e == -1 else e + len(terminator)
                    continue
            elif word in ("b", "c") and following == '"':
                i = _skip_quoted(src, j + 1)
                continue
            elif word == "b" and following == "'":
                i = j
                continue  # lexed as a char literal next
            i = j
        elif c.isdigit():
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            i = j
        else:
            i += 1
    return spans


def _line_marker(text: str) -> str:
    if text.startswith("///") and not text.startswith("////"):
        return "///"
    if text.startswith("//!"):
        return "//!"
    return "//"


def _block_marker(text: str) -> str:
    if text.startswith("/**") and not text.startswith("/***") and text != "/**/":
        return "/**"
    if text.startswith("/*!"):
        return "/*!"
    return "/*"


def extract_rust(source: str, path: str) -> list[Comment]:
    lines = split_lines(source)
    line_starts = [0]
    for idx, ch in enumerate(source):
        if ch == "\n":
            line_starts.append(idx + 1)

    def pos(off: int) -> tuple[int, int]:
        row = bisect.bisect_right(line_starts, off) - 1
        return row + 1, off - line_starts[row]

    out: list[Comment] = []
    group: list[tuple[int, int, str, str]] = []  # (row, col, marker, raw body)

    def flush() -> None:
        if not group:
            return
        row, col, marker, _ = group[0]
        last_row = group[-1][0]
        body, pad = parse_line_body([g[3] for g in group])
        out.append(
            Comment(
                path,
                "rust",
                Kind.LINE,
                row,
                last_row,
                col,
                len(lines[last_row - 1]),
                lines[row - 1][:col],
                marker,
                body,
                pad,
            )
        )
        group.clear()

    for kind, s, e in _lex(source):
        row, col = pos(s)
        line = lines[row - 1]
        if kind == "line":
            text = source[s:e].removesuffix("\r")
            marker = _line_marker(text)
            raw_body = text[len(marker) :]
            if line[:col].strip():
                flush()
                body, pad = parse_line_body([raw_body])
                out.append(
                    Comment(
                        path, "rust", Kind.TRAILING, row, row, col, col + len(text), leading_ws(line), marker, body, pad
                    )
                )
                continue
            if group and (group[-1][0] != row - 1 or group[-1][1] != col or group[-1][2] != marker):
                flush()
            group.append((row, col, marker, raw_body))
        else:
            flush()
            text = source[s:e]
            marker = _block_marker(text)
            end_row, end_col = pos(e)
            indent = leading_ws(line)
            body, style = parse_delimited(
                text[len(marker) : -2], marker, "*/", indent + " * ", indent + " ", star_ok=True
            )
            out.append(
                Comment(path, "rust", Kind.BLOCK, row, end_row, col, end_col, indent, marker, body, style.pad, style)
            )
    flush()
    return out
