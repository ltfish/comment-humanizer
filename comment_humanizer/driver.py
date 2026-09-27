"""A Linux/macOS driver whose input loop honours short escape delays.

Textual's loop only checks the parser's escape timeout after `select(0.1)` returns, so a lone
Escape costs ~100 ms whatever ESCDELAY is. This loop wakes exactly at the pending deadline, and
resolves an expired escape before feeding the next bytes.
"""

from __future__ import annotations

import os
import selectors
from codecs import getincrementaldecoder

from textual._loop import loop_last
from textual._parser import ParseError
from textual._time import get_time
from textual._xterm_parser import XTermParser
from textual.drivers.linux_driver import LinuxDriver

IDLE_POLL = 0.1  # what Textual uses; also bounds how late the exit event is noticed


def supports_deadline() -> bool:
    # the deadline is a private attribute of Textual's parser; fall back if it disappears
    return hasattr(XTermParser(False), "_timeout_time")


class FastEscapeDriver(LinuxDriver):
    def run_input_thread(self) -> None:
        if not supports_deadline():
            super().run_input_thread()
            return

        selector = selectors.SelectSelector()
        selector.register(self.fileno, selectors.EVENT_READ)
        parser = XTermParser(self._debug)
        decode = getincrementaldecoder("utf-8")().decode

        def process(selector_events: list[tuple[selectors.SelectorKey, int]], final: bool = False) -> None:
            # resolve an expired escape first: Textual's parser would glue a late key onto it (alt+key)
            for event in parser.tick():
                self.process_message(event)
            for last, (_key, mask) in loop_last(selector_events):
                if mask & selectors.EVENT_READ:
                    data = decode(os.read(self.fileno, 1024 * 4), final=final and last)
                    if not data:
                        break
                    for event in parser.feed(data):
                        self.process_message(event)
            for event in parser.tick():
                self.process_message(event)

        def timeout() -> float:
            deadline: float | None = parser._timeout_time
            if deadline is None:
                return IDLE_POLL
            return min(IDLE_POLL, max(0.0, deadline - get_time()))

        try:
            while not self.exit_event.is_set():
                process(selector.select(timeout()))
            selector.unregister(self.fileno)
            process(selector.select(IDLE_POLL), final=True)
        finally:
            selector.close()
            try:
                for _event in parser.feed(""):
                    pass
            except (EOFError, ParseError):
                pass
