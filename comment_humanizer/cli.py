from __future__ import annotations

import argparse
import os
import sys

from .gitdiff import GitError, repo_root, resolve_base
from .session import Session

DEFAULT_ESCDELAY_MS = 25  # Textual's default is 100; neovim's ttimeoutlen is 50


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="comment-humanizer",
        description="Review and rewrite Python and Rust comments added on this branch or in the last commit.",
    )
    p.add_argument("paths", nargs="*", help="limit to these files or directories")
    p.add_argument("-C", "--repo", default=".", help="repository to work in (default: current directory)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--last-commit", action="store_true", help="comments added by the latest commit")
    mode.add_argument("--base", help="compare against the merge base with this ref (default: master, then main)")
    p.add_argument("--author", help="author for commits made from the TUI")
    p.add_argument("--no-verify", action="store_true", help="skip commit hooks")
    p.add_argument("--list", action="store_true", help="print the comments and exit")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = repo_root(args.repo)
        base = resolve_base(root, last_commit=args.last_commit, base=args.base)
        specs = [os.path.relpath(os.path.abspath(os.path.join(args.repo, p)), root) for p in args.paths] or None
        session = Session(root, base, specs, author=args.author, no_verify=args.no_verify)
    except GitError as e:
        print(f"comment-humanizer: {e}", file=sys.stderr)
        return 2

    if args.list:
        for item in session.items:
            c = item.comment
            print(f"{c.path}:{c.start_line}\t{c.kind.value}\t{c.preview()}")
        return 0

    # Textual reads ESCDELAY when it is first imported
    os.environ.setdefault("ESCDELAY", str(DEFAULT_ESCDELAY_MS))
    from .tui import HumanizerApp  # keep --list usable without loading textual

    HumanizerApp(session).run()
    return 0
