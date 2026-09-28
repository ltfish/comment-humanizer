"""A small vim normal-mode model: motions, operators, registers and undo over a list of lines."""

from __future__ import annotations

import re
from dataclasses import dataclass

_PENDING = re.compile(r"([1-9]\d*)?(?:([dcy])([1-9]\d*)?)?(.*)", re.DOTALL)
_VISUAL_PENDING = re.compile(r"([1-9]\d*)?(.*)", re.DOTALL)
# visual-mode keys that act on the selection
VISUAL_OPS = {"d", "x", "c", "s", "y", "p", "P", "J", "~", "u", "U"}
MOTIONS = {"h", "j", "k", "l", "w", "b", "e", "0", "^", "$", "G", "gg"}
LINEWISE_MOTIONS = {"j", "k", "G", "gg"}
INCLUSIVE_MOTIONS = {"e", "$"}


def _cls(ch: str) -> int:
    if ch.isspace():
        return 0
    return 1 if ch.isalnum() or ch == "_" else 2


@dataclass
class Motion:
    row: int
    col: int
    linewise: bool = False
    inclusive: bool = False


class VimBuffer:
    """Normal-mode state. `feed` returns "insert", "command", "leave" or None."""

    def __init__(self, text: str = ""):
        self.lines: list[str] = [""]
        self.row = 0
        self.col = 0
        self.pending = ""
        self.register = ("", False)  # (text, linewise)
        self.undo_stack: list[tuple[list[str], int, int]] = []
        self.redo_stack: list[tuple[list[str], int, int]] = []
        self.visual: str | None = None  # "v" (charwise) or "V" (linewise)
        self.anchor = (0, 0)
        self.eol = False  # visual `$`: the selection runs through the line break
        self.replacing = False
        # originals overwritten in this replace session; None marks an appended char or line break
        self.replaced: list[str | None] = []
        self.reset(text)

    # state

    def reset(self, text: str) -> None:
        self.lines = text.split("\n")
        self.row = self.col = 0
        self.pending = ""
        self.visual = None
        self.replacing = False
        self.replaced.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def _snapshot(self) -> None:
        self.undo_stack.append((list(self.lines), self.row, self.col))
        self.redo_stack.clear()

    def clamp(self) -> None:
        self.row = max(0, min(self.row, len(self.lines) - 1))
        past_end = (self.visual and self.eol) or self.replacing
        last = len(self.lines[self.row]) if past_end else len(self.lines[self.row]) - 1
        self.col = max(0, min(self.col, max(last, 0)))

    def end_insert(self) -> None:
        """Leaving insert mode: drop a no-op undo step and step the cursor back like vim."""
        if self.undo_stack and self.undo_stack[-1][0] == self.lines:
            self.undo_stack.pop()
        self.col -= 1
        self.clamp()

    # offsets

    def _offset(self, row: int, col: int) -> int:
        return sum(len(line) + 1 for line in self.lines[:row]) + col

    def _position(self, offset: int) -> tuple[int, int]:
        for row, line in enumerate(self.lines):
            if offset <= len(line):
                return row, offset
            offset -= len(line) + 1
        return len(self.lines) - 1, len(self.lines[-1])

    def _first_nonblank(self, row: int) -> int:
        line = self.lines[row]
        return len(line) - len(line.lstrip())

    # word motions over the flattened text; an empty line counts as a word

    def _word_forward(self, off: int, text: str) -> int:
        n = len(text)
        if off >= n:
            return n
        c = _cls(text[off])
        if c:
            while off < n and _cls(text[off]) == c:
                off += 1
        while off < n and text[off].isspace():
            if text[off] == "\n" and off + 1 < n and text[off + 1] == "\n":
                return off + 1
            off += 1
        return off

    def _word_end(self, off: int, text: str) -> int:
        n = len(text)
        off += 1
        while off < n and text[off].isspace():
            off += 1
        if off >= n:
            return max(n - 1, 0)
        c = _cls(text[off])
        while off + 1 < n and _cls(text[off + 1]) == c:
            off += 1
        return off

    def _word_back(self, off: int, text: str) -> int:
        if off <= 0:
            return 0
        off -= 1
        while off > 0 and text[off].isspace():
            if text[off] == "\n" and text[off - 1] == "\n":
                return off
            off -= 1
        c = _cls(text[off])
        while off > 0 and _cls(text[off - 1]) == c:
            off -= 1
        return off

    def _motion(self, name: str, count: int, explicit: bool) -> Motion:
        row, col = self.row, self.col
        last = len(self.lines) - 1
        if name == "h":
            return Motion(row, max(col - count, 0))
        if name == "l":
            return Motion(row, min(col + count, len(self.lines[row])))
        if name in ("j", "k"):
            target = min(row + count, last) if name == "j" else max(row - count, 0)
            return Motion(target, col, linewise=True)
        if name == "0":
            return Motion(row, 0)
        if name == "^":
            return Motion(row, self._first_nonblank(row))
        if name == "$":
            target = min(row + count - 1, last)
            return Motion(target, max(len(self.lines[target]) - 1, 0), inclusive=True)
        if name in ("G", "gg"):
            target = min(count - 1, last) if explicit else (last if name == "G" else 0)
            return Motion(target, self._first_nonblank(target), linewise=True)
        text = self.text
        off = self._offset(row, col)
        step = {"w": self._word_forward, "e": self._word_end, "b": self._word_back}[name]
        for _ in range(count):
            off = step(off, text)
        r, c = self._position(off)
        return Motion(r, c, inclusive=name == "e")

    # operators

    def _apply(self, op: str, m: Motion) -> str | None:
        if m.linewise:
            r1, r2 = sorted((self.row, m.row))
            chunk = self.lines[r1 : r2 + 1]
            self.register = ("\n".join(chunk), True)
            if op == "y":
                self.row = r1
                return None
            self._snapshot()
            if op == "c":
                self.lines[r1 : r2 + 1] = [""]
                self.row, self.col = r1, 0
                return "insert"
            self.lines[r1 : r2 + 1] = []
            if not self.lines:
                self.lines = [""]
            self.row = min(r1, len(self.lines) - 1)
            self.col = self._first_nonblank(self.row)
            return None

        a = self._offset(self.row, self.col)
        b = self._offset(m.row, m.col)
        start, end = min(a, b), max(a, b)
        if m.inclusive and m.col < len(self.lines[m.row]):
            end += 1  # never swallow the line break under an empty line's cursor
        text = self.text
        end = min(end, len(text))
        self.register = (text[start:end], False)
        if op == "y":
            self.row, self.col = self._position(start)
            return None
        self._snapshot()
        self.lines = (text[:start] + text[end:]).split("\n")
        self.row, self.col = self._position(start)
        return "insert" if op == "c" else None

    def _operate(self, op: str, motion: str, count: int, explicit: bool) -> str | None:
        if motion == op:  # dd, cc, yy
            return self._apply(op, Motion(min(self.row + count - 1, len(self.lines) - 1), 0, linewise=True))
        if op == "c" and motion == "w" and _cls(self._char_at(self.row, self.col)):
            motion = "e"  # cw changes to the end of the word, like vim
        m = self._motion(motion, count, explicit)
        if op in "dc" and motion == "w" and m.row > self.row:
            # dw on a line's last word stops at the end of the line
            m = Motion(self.row, len(self.lines[self.row]))
        return self._apply(op, m)

    def _char_at(self, row: int, col: int) -> str:
        line = self.lines[row]
        return line[col] if col < len(line) else " "

    # simple commands

    def _open_line(self, below: bool) -> str:
        self._snapshot()
        at = self.row + 1 if below else self.row
        self.lines.insert(at, "")
        self.row, self.col = at, 0
        return "insert"

    def _put(self, after: bool, count: int) -> None:
        text, linewise = self.register
        if not text and not linewise:
            return
        self._snapshot()
        if linewise:
            new = text.split("\n") * count
            at = self.row + 1 if after else self.row
            self.lines[at:at] = new
            self.row = at
            self.col = self._first_nonblank(at)
            return
        line = self.lines[self.row]
        at = min(self.col + 1, len(line)) if after and line else self.col
        off = self._offset(self.row, at)
        whole = self.text
        insert = text * count
        self.lines = (whole[:off] + insert + whole[off:]).split("\n")
        self.row, self.col = self._position(off + len(insert) - 1)

    def undo(self) -> None:
        if self.undo_stack:
            self.redo_stack.append((list(self.lines), self.row, self.col))
            self.lines, self.row, self.col = self.undo_stack.pop()

    def redo(self) -> None:
        if self.redo_stack:
            self.undo_stack.append((list(self.lines), self.row, self.col))
            self.lines, self.row, self.col = self.redo_stack.pop()

    def _command(self, key: str, count: int, explicit: bool) -> str | None:
        line = self.lines[self.row]
        if key == "R":
            self._snapshot()
            self.replacing = True
            self.replaced.clear()
            return None
        if len(key) == 2 and key[0] == "r":
            self._replace_chars(count, key[1])
            return None
        if key in ("v", "V"):
            self.visual = key
            self.eol = False
            self.anchor = (self.row, self.col)
            return None
        if key in ("i", "a", "I", "A"):
            self._snapshot()
            self.col = {
                "i": self.col,
                "a": min(self.col + 1, len(line)),
                "I": self._first_nonblank(self.row),
                "A": len(line),
            }[key]
            return "insert"
        if key in ("o", "O"):
            return self._open_line(key == "o")
        if key == "x":
            if line:
                return self._apply("d", Motion(self.row, min(self.col + count, len(line))))
            return None
        if key in ("D", "C"):
            return self._operate("d" if key == "D" else "c", "$", count, explicit)
        if key in ("p", "P"):
            self._put(key == "p", count)
            return None
        if key == "u":
            for _ in range(count):
                self.undo()
            return None
        if key == ":":
            return "command"
        return None

    def feed(self, key: str) -> str | None:
        """Process one key. Printable keys are their character; others use Textual key names."""
        if self.replacing:
            self._replace_feed(key)
            self.clamp()
            return None
        if key == "enter" and not self.visual and self.pending and self.pending[-1] == "r":
            key = "\n"  # r<enter> replaces the character with a line break
        if self.visual:
            result = self._visual_feed(key)
            if not self.visual:
                self.eol = False
            if result != "insert":
                self.clamp()
            return result
        result: str | None = None
        if key == "escape":
            leave = not self.pending
            self.pending = ""
            return "leave" if leave else None
        if key == "ctrl+r":
            self.pending = ""
            self.redo()
        elif key in ("enter", "backspace", "delete"):
            self.pending = ""
            if key == "enter":
                self.row = min(self.row + 1, len(self.lines) - 1)
                self.col = self._first_nonblank(self.row)
            elif key == "backspace":
                self.col -= 1
            else:
                result = self._command("x", 1, False)
        elif len(key) == 1:
            self.pending += key
            result = self._step()
        else:
            self.pending = ""
        if result != "insert":
            self.clamp()
        return result

    def _step(self) -> str | None:
        m = _PENDING.fullmatch(self.pending)
        assert m is not None
        c1, op, c2, rest = m.groups()
        if not rest or rest == "g" or (rest == "r" and not op):
            return None  # wait for more keys
        self.pending = ""
        explicit = bool(c1 or c2)
        count = int(c1 or 1) * int(c2 or 1)
        if op:
            if rest in MOTIONS or rest == op:
                return self._operate(op, rest, count, explicit)
            return None
        if rest in MOTIONS:
            target = self._motion(rest, count, explicit)
            self.row, self.col = target.row, target.col
            if rest in ("j", "k"):
                self.col = min(self.col, max(len(self.lines[self.row]) - 1, 0))
            return None
        return self._command(rest, count, explicit)

    # visual mode

    def selection(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """Ordered (start, end) of the selection; end is inclusive."""
        a, b = self.anchor, (self.row, self.col)
        return (a, b) if a <= b else (b, a)

    def _visual_feed(self, key: str) -> str | None:
        if key == "escape":
            self.pending = ""
            self.visual = None
            return None
        if self.pending.endswith("r") and len(key) != 1:
            self.pending = ""  # r needs a character; a line break is not supported here
            return None
        key = {"enter": "j", "backspace": "h", "delete": "x"}.get(key, key)
        if len(key) != 1:
            self.pending = ""
            return None
        self.pending += key
        m = _VISUAL_PENDING.fullmatch(self.pending)
        assert m is not None
        c1, rest = m.groups()
        if not rest or rest in ("g", "r"):
            return None
        self.pending = ""
        count = int(c1 or 1)
        if len(rest) == 2 and rest[0] == "r":
            self._visual_replace(rest[1])
            return None
        if rest in MOTIONS:
            target = self._motion(rest, count, bool(c1))
            self.row, self.col = target.row, target.col
            self.eol = rest == "$"
            if self.eol:
                self.col = len(self.lines[self.row])
        elif rest == "o":
            self.anchor, (self.row, self.col) = (self.row, self.col), self.anchor
        elif rest in ("v", "V"):
            self.visual = None if rest == self.visual else rest
        elif rest == ":":
            self.visual = None
            return "command"
        elif rest in VISUAL_OPS:
            return self._visual_op(rest)
        return None

    def _char_range(self) -> tuple[int, int]:
        (r1, c1), (r2, c2) = self.selection()
        # the character under the cursor is selected; on an empty line that is its line break
        return self._offset(r1, c1), min(self._offset(r2, c2) + 1, len(self.text))

    def _visual_op(self, op: str) -> str | None:
        linewise = self.visual == "V"
        (r1, _), (r2, _) = self.selection()
        self.visual = None
        self.eol = False
        if op in ("d", "x", "c", "s", "y"):
            kind = {"x": "d", "s": "c"}.get(op, op)
            if linewise:
                self.row, self.col = r1, 0
                return self._apply(kind, Motion(r2, 0, linewise=True))
            start, end = self._char_range()
            text = self.text
            self.register = (text[start:end], False)
            if kind != "y":
                self._snapshot()
                self.lines = (text[:start] + text[end:]).split("\n")
            self.row, self.col = self._position(start)
            return "insert" if kind == "c" else None
        self._snapshot()
        if op in ("p", "P"):
            kept = self.register
            self._visual_put(linewise, r1, r2)
            if op == "P":
                self.register = kept
        elif op == "J":
            self._join(r1, max(r2, r1 + 1))
        else:
            convert = {"~": str.swapcase, "u": str.lower, "U": str.upper}[op]
            if linewise:
                self.lines[r1 : r2 + 1] = [convert(line) for line in self.lines[r1 : r2 + 1]]
                self.row, self.col = r1, 0
            else:
                start, end = self._char_range()
                text = self.text
                self.lines = (text[:start] + convert(text[start:end]) + text[end:]).split("\n")
                self.row, self.col = self._position(start)
        if self.undo_stack and self.undo_stack[-1][0] == self.lines:
            self.undo_stack.pop()  # nothing changed
        return None

    def _visual_put(self, linewise: bool, r1: int, r2: int) -> None:
        put, put_linewise = self.register
        if linewise:
            self.register = ("\n".join(self.lines[r1 : r2 + 1]), True)
            self.lines[r1 : r2 + 1] = put.split("\n")
            self.row, self.col = r1, self._first_nonblank(r1)
            return
        start, end = self._char_range()
        text = self.text
        self.register = (text[start:end], False)
        insert = "\n" + put + "\n" if put_linewise else put
        self.lines = (text[:start] + insert + text[end:]).split("\n")
        self.row, self.col = self._position(start + len(insert) - 1 if not put_linewise else start + 1)

    def _join(self, r1: int, r2: int) -> None:
        r2 = min(r2, len(self.lines) - 1)
        joined = self.lines[r1]
        col = len(joined)
        for line in self.lines[r1 + 1 : r2 + 1]:
            piece = line.lstrip()
            col = len(joined)
            if piece:
                joined = (joined.rstrip() + " " + piece) if joined.strip() else piece
                col = len(joined) - len(piece) - 1 if joined != piece else 0
        self.lines[r1 : r2 + 1] = [joined]
        self.row, self.col = r1, col

    # replace mode

    def _replace_chars(self, count: int, ch: str) -> None:
        """`r`: overwrite `count` characters; does nothing if the line is too short, like vim."""
        line = self.lines[self.row]
        if self.col + count > len(line):
            return
        self._snapshot()
        if ch == "\n":
            self.lines[self.row : self.row + 1] = [line[: self.col], line[self.col + count :]]
            self.row, self.col = self.row + 1, 0
            return
        self.lines[self.row] = line[: self.col] + ch * count + line[self.col + count :]
        self.col += count - 1

    def _visual_replace(self, ch: str) -> None:
        linewise = self.visual == "V"
        (r1, _), (r2, _) = self.selection()
        self.visual = None
        self.eol = False
        self._snapshot()
        if linewise:
            self.lines[r1 : r2 + 1] = [ch * len(line) for line in self.lines[r1 : r2 + 1]]
            self.row, self.col = r1, 0
        else:
            start, end = self._char_range()
            text = self.text
            middle = "".join(c if c == "\n" else ch for c in text[start:end])
            self.lines = (text[:start] + middle + text[end:]).split("\n")
            self.row, self.col = self._position(start)
        if self.undo_stack[-1][0] == self.lines:
            self.undo_stack.pop()

    def _replace_feed(self, key: str) -> None:
        line = self.lines[self.row]
        if key == "escape":
            self.replacing = False
            self.replaced.clear()
            if self.undo_stack and self.undo_stack[-1][0] == self.lines:
                self.undo_stack.pop()
            self.col -= 1
        elif key == "enter":
            self.lines[self.row : self.row + 1] = [line[: self.col], line[self.col :]]
            self.row, self.col = self.row + 1, 0
            self.replaced.append(None)
        elif key == "backspace":
            if not self.replaced:
                self.col = max(self.col - 1, 0)  # outside this session's text: only move
                return
            original = self.replaced.pop()
            if self.col == 0:  # undo a line break typed in this session
                prev = self.lines[self.row - 1]
                self.lines[self.row - 1 : self.row + 1] = [prev + line]
                self.row, self.col = self.row - 1, len(prev)
                return
            self.col -= 1
            rest = line[self.col + 1 :] if original is None else original + line[self.col + 1 :]
            self.lines[self.row] = line[: self.col] + rest
        elif key in ("left", "right", "up", "down", "home", "end"):
            self.replaced.clear()  # like vim, moving ends what backspace can restore
            if key in ("left", "right"):
                self.col += 1 if key == "right" else -1
            elif key in ("up", "down"):
                self.row += 1 if key == "down" else -1
            else:
                self.col = 0 if key == "home" else len(self.lines[self.row])
        elif len(key) == 1:
            self.replaced.append(line[self.col] if self.col < len(line) else None)
            self.lines[self.row] = line[: self.col] + key + line[self.col + 1 :]
            self.col += 1
