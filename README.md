# comment-humanizer

A TUI for reviewing and rewriting the Python and Rust comments (including docstrings) added on the
current branch or in the latest commit.

```
comment-humanizer                 # comments added since the merge base with master (or main)
comment-humanizer --base develop  # ... with another branch
comment-humanizer --last-commit   # comments added by HEAD
comment-humanizer --list src/     # print instead of opening the TUI; paths limit the scope
```

Uncommitted and untracked changes count as added. The base is resolved to a SHA at startup, so
committing from inside the tool does not change the list.

## What counts as a comment

- Python: runs of `#` comments on consecutive lines at the same indent, trailing `#` comments, and
  module/class/function docstrings. Tool directives (`# noqa`, `# type:`, `# fmt:` ...) and shebangs
  are ignored.
- Rust: runs of `//`, `///` or `//!` comments, trailing `//` comments, and `/* */` blocks
  (nested, `/** */`, `/*! */`, with or without ` * ` line prefixes).

A comment is listed if any of its lines was added.

## Editing

The editor shows the comment text without the comment syntax; saving puts the markers, quotes,
` * ` prefixes and indentation back. Comments can grow or shrink to any number of lines. A trailing
comment that grows past one line moves above its code line. An empty body deletes a line comment.
Every save is re-parsed and refused if the text would not read back as the same comment (e.g.
`*/` inside a block comment or `"""` inside a docstring).

In the list:

| Key | Action |
| --- | --- |
| `j` / `k`, arrows | move |
| `enter` | edit the selected comment |
| `r` | revert the comment to its original text |
| `x` | mark as skipped / pending |
| `f` | cycle the status filter |
| `c` | commit the edits made so far |
| `q` | quit (asks if edits are uncommitted) |

The editor is vim-style and opens in normal mode; the bottom border shows the mode and the `:`
command being typed.

- Motions: `h j k l`, `w b e`, `0 ^ $`, `gg G`, with counts (`3w`, `2dd`, `5G`).
- Insert: `i a I A o O`; `esc` returns to normal mode.
- Edits: `x`, `dd`, `dw`, `de`, `D`, `cw`, `cc`, `C`, `yy`, `yw`, `p`, `P`, and operators with any
  motion above; `u` undo, `ctrl+r` redo.
- `:w` saves into the file, `:wq` / `:x` save and go back to the list, `:q` goes back (refused with
  unsaved changes), `:q!` discards them. `esc` in normal mode also goes back when nothing is unsaved.
- `ctrl+s` saves from any mode.

## Committing part-way

`c` commits only the changes made in the tool: the patch is applied to a temporary index built from
HEAD, so other staged or unstaged work stays where it is. Use `--author` to set the commit author and
`--no-verify` to skip hooks.

## Development

```
pip install -e '.[test]'
pytest            # runs with -n auto
```
