from __future__ import annotations

import ast
import io
import re
import tokenize

from ..models import Comment, Kind
from .common import leading_ws, parse_delimited, parse_line_body, split_lines

# tool directives are not prose
_PRAGMA = re.compile(r"^\s*(noqa\b|type:|pylint:|pragma:|fmt:|isort:|mypy:|pyright:|ruff:|-\*-)")
_DOC_OPEN = re.compile(r"([rRuU]*)(\"\"\"|'''|\"|')")


def _char_col(line: str, byte_col: int) -> int:
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def _line_comments(source: str, path: str, lines: list[str]) -> list[Comment]:
    tokens: list[tuple[int, int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                tokens.append((tok.start[0], tok.start[1], tok.string))
    except (tokenize.TokenError, SyntaxError):
        pass

    out: list[Comment] = []
    group: list[tuple[int, int, str]] = []

    def flush() -> None:
        if not group:
            return
        row, col, _ = group[0]
        last_row = group[-1][0]
        body, pad = parse_line_body([t[2][1:] for t in group])
        out.append(
            Comment(
                path,
                "python",
                Kind.LINE,
                row,
                last_row,
                col,
                len(lines[last_row - 1]),
                lines[row - 1][:col],
                "#",
                body,
                pad,
            )
        )
        group.clear()

    for row, col, text in tokens:
        if row == 1 and text.startswith("#!"):
            continue
        if _PRAGMA.match(text[1:]):
            continue
        line = lines[row - 1]
        if line[:col].strip():
            body, pad = parse_line_body([text[1:]])
            out.append(
                Comment(path, "python", Kind.TRAILING, row, row, col, col + len(text), leading_ws(line), "#", body, pad)
            )
            continue
        if group and (group[-1][0] != row - 1 or group[-1][1] != col):
            flush()
        group.append((row, col, text))
    flush()
    return out


def _docstrings(source: str, path: str, lines: list[str]) -> list[Comment]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    out: list[Comment] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.body:
            continue
        expr = node.body[0]
        if not (
            isinstance(expr, ast.Expr) and isinstance(expr.value, ast.Constant) and isinstance(expr.value.value, str)
        ):
            continue
        assert expr.end_lineno is not None and expr.end_col_offset is not None
        start_line, end_line = expr.lineno, expr.end_lineno
        start_col = _char_col(lines[start_line - 1], expr.col_offset)
        end_col = _char_col(lines[end_line - 1], expr.end_col_offset)
        if start_line == end_line:
            raw = lines[start_line - 1][start_col:end_col]
        else:
            raw = "\n".join(
                [lines[start_line - 1][start_col:], *lines[start_line : end_line - 1], lines[end_line - 1][:end_col]]
            )
        m = _DOC_OPEN.match(raw)
        if m is None:
            continue
        prefix, quote = m.group(1), m.group(2)
        if not raw.endswith(quote) or len(raw) < len(m.group(0)) + len(quote):
            continue
        inner = raw[m.end() : len(raw) - len(quote)]
        # skip implicit concatenation such as """a""" """b"""
        if quote in inner.replace("\\\\", "").replace("\\" + quote[0], ""):
            continue
        indent = leading_ws(lines[start_line - 1])
        body, style = parse_delimited(inner, prefix + quote, quote, indent, indent, star_ok=False)
        out.append(
            Comment(
                path,
                "python",
                Kind.DOCSTRING,
                start_line,
                end_line,
                start_col,
                end_col,
                indent,
                prefix + quote,
                body,
                style.pad,
                style,
            )
        )
    return out


def extract_python(source: str, path: str) -> list[Comment]:
    lines = split_lines(source)
    comments = _line_comments(source, path, lines) + _docstrings(source, path, lines)
    comments.sort(key=lambda c: (c.start_line, c.start_col))
    return comments
