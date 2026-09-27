"""Drive the real CLI through a pseudo-terminal, covering raw terminal key decoding."""

import fcntl
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="needs a pty")


def _drain_until(fd, pred, timeout):
    """Keep reading the terminal (so the app never blocks on output) until pred() holds."""
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                os.read(fd, 65536)
            except OSError:
                return pred()
    return pred()


def test_vim_write_in_real_terminal(repo):
    repo.commit("base", **{"a.py": "x = 1\n"})
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("feat", **{"a.py": "# old comment\nx = 1\n"})

    fd, child_fd = pty.openpty()
    fcntl.ioctl(child_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    proc = subprocess.Popen(
        [sys.executable, "-m", "comment_humanizer"],
        cwd=repo.root,
        stdin=child_fd,
        stdout=child_fd,
        stderr=child_fd,
        env={**os.environ, "TERM": "xterm-256color"},
        start_new_session=True,
    )
    os.close(child_fd)
    try:
        # wait for the first full paint: some output, then a short quiet period
        got, quiet_since = 0, time.time()
        end = time.time() + 20
        while time.time() < end and not (got and time.time() - quiet_since > 0.5):
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                got += len(os.read(fd, 65536))
                quiet_since = time.time()
        assert got
        for keys in (b"\r", b"cw", b"new", b"\x1b", b":w\r"):
            os.write(fd, keys)
            # keep reading so the app never blocks on output; the pause also lets a bare ESC register
            _drain_until(fd, lambda: False, 0.15)
        assert _drain_until(fd, lambda: repo.read("a.py").startswith("# new comment\n"), 10), repo.read("a.py")
    finally:
        proc.kill()
        proc.wait()
        os.close(fd)
