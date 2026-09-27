from __future__ import annotations

import os
import re
import subprocess

from .extract import LANGUAGES

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
PATHSPECS = [f"*{ext}" for ext in LANGUAGES]
_HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")


class GitError(Exception):
    pass


def git(repo: str, *args: str, stdin: str | None = None, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        input=stdin,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, **env} if env else None,
    )
    if proc.returncode != 0:
        raise GitError((proc.stderr or proc.stdout).strip() or f"git {args[0]} failed")
    return proc.stdout


def repo_root(path: str) -> str:
    return git(path, "rev-parse", "--show-toplevel").strip()


def _ref_exists(repo: str, ref: str) -> bool:
    try:
        git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except GitError:
        return False
    return True


def default_base_ref(repo: str) -> str:
    for ref in ("master", "main", "origin/master", "origin/main"):
        if _ref_exists(repo, ref):
            return ref
    raise GitError("cannot find a master or main branch; pass --base")


def resolve_base(repo: str, last_commit: bool = False, base: str | None = None) -> str:
    """Resolve the comparison point to a fixed SHA, so later commits do not move it."""
    if last_commit:
        if _ref_exists(repo, "HEAD~1"):
            return git(repo, "rev-parse", "HEAD~1").strip()
        return EMPTY_TREE
    ref = base or default_base_ref(repo)
    if not _ref_exists(repo, ref):
        raise GitError(f"unknown revision: {ref}")
    return git(repo, "merge-base", "HEAD", ref).strip()


def _unquote(path: str) -> str:
    if path.startswith('"') and path.endswith('"'):
        raw = path[1:-1].encode("latin-1", errors="backslashreplace").decode("unicode_escape")
        return raw.encode("latin-1").decode("utf-8", errors="replace")
    return path


def parse_diff(diff: str) -> dict[str, set[int]]:
    added: dict[str, set[int]] = {}
    current: set[int] | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = _unquote(line[4:].rstrip("\t"))
            if target == "/dev/null":
                current = None
            else:
                current = added.setdefault(target.removeprefix("b/"), set())
        elif line.startswith("@@") and current is not None:
            m = _HUNK.match(line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) is not None else 1
                current.update(range(start, start + count))
    return {path: lines for path, lines in added.items() if lines}


def added_lines(repo: str, base: str, pathspecs: list[str] | None = None) -> dict[str, set[int]]:
    """Lines added between `base` and the working tree, including untracked files."""
    specs = pathspecs or PATHSPECS
    diff = git(
        repo, "-c", "core.quotePath=false", "diff", "-U0", "-M", "--no-color", "--no-ext-diff", base, "--", *specs
    )
    added = parse_diff(diff)
    untracked = git(repo, "ls-files", "--others", "--exclude-standard", "-z", "--", *specs)
    for path in filter(None, untracked.split("\0")):
        try:
            with open(os.path.join(repo, path), encoding="utf-8", newline="") as f:
                n = f.read().count("\n") + 1
        except (OSError, UnicodeDecodeError):
            continue
        added[path] = set(range(1, n + 1))
    return {p: lines for p, lines in added.items() if p.endswith(tuple(LANGUAGES))}
