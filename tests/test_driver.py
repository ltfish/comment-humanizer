import sys

import pytest
from textual.drivers.linux_driver import LinuxDriver

from comment_humanizer import driver as driver_mod
from comment_humanizer.driver import FastEscapeDriver, supports_deadline
from comment_humanizer.tui import HumanizerApp


def test_parser_exposes_deadline():
    # if a Textual upgrade removes it, the driver silently falls back; this flags it
    assert supports_deadline()


@pytest.mark.skipif(sys.platform == "win32", reason="Linux/macOS driver only")
def test_app_uses_fast_driver():
    assert HumanizerApp.get_driver_class(object.__new__(HumanizerApp)) is FastEscapeDriver


def test_falls_back_to_stock_loop(monkeypatch):
    called = []
    monkeypatch.setattr(driver_mod, "supports_deadline", lambda: False)
    monkeypatch.setattr(LinuxDriver, "run_input_thread", lambda self: called.append(self))
    drv = object.__new__(FastEscapeDriver)
    drv.run_input_thread()
    assert called == [drv]
