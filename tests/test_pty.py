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
        r, _, _ = select.select([fd], [], [], 0.01)
        if r:
            try:
                os.read(fd, 65536)
            except OSError:
                return pred()
    return pred()


class Term:
    def __init__(self, repo, escdelay=None):
        self.fd, child_fd = pty.openpty()
        fcntl.ioctl(child_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        env = {k: v for k, v in os.environ.items() if k != "ESCDELAY"}
        env["TERM"] = "xterm-256color"
        if escdelay is not None:
            env["ESCDELAY"] = str(escdelay)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "comment_humanizer"],
            cwd=repo.root,
            stdin=child_fd,
            stdout=child_fd,
            stderr=child_fd,
            env=env,
            start_new_session=True,
        )
        os.close(child_fd)
        # wait for the first full paint: some output, then a short quiet period
        got, quiet_since = 0, time.time()
        end = time.time() + 20
        while time.time() < end and not (got and time.time() - quiet_since > 0.5):
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if r:
                got += len(os.read(self.fd, 65536))
                quiet_since = time.time()
        assert got

    def send(self, *chunks, gap=0.15):
        for chunk in chunks:
            os.write(self.fd, chunk)
            _drain_until(self.fd, lambda: False, gap)

    def wait(self, pred, timeout=10):
        return _drain_until(self.fd, pred, timeout)

    def close(self):
        self.proc.kill()
        self.proc.wait()
        os.close(self.fd)


@pytest.fixture
def feature(repo):
    repo.commit("base", **{"a.py": "x = 1\n"})
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("feat", **{"a.py": "# old comment\nx = 1\n"})
    return repo


def run_keys(repo, chunks, escdelay=None, gap=0.15):
    term = Term(repo, escdelay)
    try:
        term.send(*chunks, gap=gap)
        return term.wait(lambda: repo.read("a.py") != "# old comment\nx = 1\n", timeout=2)
    finally:
        term.close()


def test_vim_write_in_real_terminal(feature):
    assert run_keys(feature, [b"\r", b"cw", b"new", b"\x1b", b":w\r"])
    assert feature.read("a.py") == "# new comment\nx = 1\n"


def test_escape_resolves_before_a_key_60ms_later(feature):
    # with Textual's stock input loop the late `x` is glued onto the escape as alt+x
    assert run_keys(feature, [b"\r", b"A", b"\x1b", b"x", b":w\r"], gap=0.06)
    assert feature.read("a.py") == "# old commen\nx = 1\n"


def test_user_escdelay_takes_precedence(feature):
    # 400 ms: escape and the `x` 60 ms later form alt+x, so insert mode never ends and nothing is saved
    assert not run_keys(feature, [b"\r", b"A", b"\x1b", b"x", b":w\r"], escdelay=400, gap=0.06)


def test_arrow_keys_still_parse(feature):
    assert run_keys(feature, [b"\r", b"\x1b[C\x1b[C", b"x", b":w\r"])
    assert feature.read("a.py") == "# ol comment\nx = 1\n"
