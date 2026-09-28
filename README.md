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
comment that grows past one line moves above its code line. Blank lines at the start or end of the
text are kept (as bare `#` lines, or blank lines inside a docstring or block comment). A body that is
empty or only whitespace deletes the comment.
Every save is re-parsed and refused if the text would not read back as the same comment (e.g.
`*/` inside a block comment or `"""` inside a docstring).

In the list:

| Key | Action |
| --- | --- |
| `j` / `k`, arrows | move |
| `enter` | edit the selected comment |
| `d` | delete the comment from the file (`r` brings it back) |
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
- Replace: `R` overwrites as you type (appending past the end of a line, `enter` breaks the line);
  `backspace` restores what was overwritten; `esc` returns to normal mode. `r{char}` replaces the
  character under the cursor (`3rx` three of them, `r` then `enter` a line break), and in visual
  mode every selected character.
- Visual: `v` (characters) and `V` (lines) select with any motion above; `o` jumps to the other end,
  `esc` or the same key again leaves. On the selection: `d`/`x` delete, `c`/`s` change, `y` yank,
  `p` replace with the register (`P` keeps the register), `J` join lines, `~`/`u`/`U` toggle, lower
  or upper case.
- `:w` saves into the file, `:wq` / `:x` save and go back to the list, `:q` goes back (refused with
  unsaved changes), `:q!` discards them. `esc` in normal mode also goes back when nothing is unsaved.
- `ctrl+s` saves from any mode.

Deleting removes a comment's lines when it has them to itself; an inline or trailing comment is cut
out of its line. A docstring is not deleted if it is the only statement in its body or shares its
line with code.

## Escape key latency

Terminals send Escape as the same byte that starts arrow-key and alt-key sequences, so a lone
Escape is only recognised after a short wait. comment-humanizer waits 25 ms (Textual's default is
100 ms, and its input loop only checked every 100 ms; the tool replaces that loop). Over a slow SSH
link, where an arrow key's bytes can arrive further apart, raise it: `ESCDELAY=100 comment-humanizer`.
Terminals that speak the kitty keyboard protocol (kitty, WezTerm, Ghostty, foot, recent Alacritty
and iTerm2) send Escape unambiguously and have no wait. tmux and screen add their own delay
(`set -sg escape-time 10` in tmux, `maptimeout 10` in screen).

## Committing part-way

`c` commits only the changes made in the tool: the patch is applied to a temporary index built from
HEAD, so other staged or unstaged work stays where it is. Use `--author` to set the commit author and
`--no-verify` to skip hooks.

## Development

```
pip install -e '.[test]'
pytest            # runs with -n auto
```
