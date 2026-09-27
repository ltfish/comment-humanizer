from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


class Repo:
    def __init__(self, root: Path):
        self.root = root
        self.git("init", "-q", "-b", "master")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout

    def write(self, path: str, text: str) -> None:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, newline="")

    def read(self, path: str) -> str:
        return (self.root / path).read_text(newline="")

    def commit(self, message: str, **files: str) -> str:
        for path, text in files.items():
            self.write(path.replace("__", "/"), text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def show(self, rev: str, path: str) -> str:
        return self.git("show", f"{rev}:{path}")


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)
