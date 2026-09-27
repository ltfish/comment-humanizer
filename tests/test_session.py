import pytest

from comment_humanizer.gitdiff import resolve_base
from comment_humanizer.models import Kind, Status
from comment_humanizer.rewrite import EditError
from comment_humanizer.session import Session

BASE_PY = "def f():\n    return 1\n"
FEAT_PY = '''# Helper that returns one.
# It is very important.
def f():
    """Return one."""
    return 1  # the value


# Unrelated old comment
X = 2
'''
FEAT_RS = """/// Adds.
fn add(a: i32, b: i32) -> i32 {
    /* sum */
    a + b
}
"""


@pytest.fixture
def feature(repo):
    repo.commit("base", **{"m.py": BASE_PY + "\n\n# Unrelated old comment\nX = 2\n"})
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("feat", **{"m.py": FEAT_PY, "r.rs": FEAT_RS})
    return repo


def open_session(repo, **kw):
    root = str(repo.root)
    return Session(root, resolve_base(root, last_commit=kw.pop("last_commit", False)), **kw)


def by_body(session, prefix):
    return next(i for i in session.items if i.comment.body.startswith(prefix))


def test_only_added_comments_are_listed(feature):
    s = open_session(feature)
    assert [(i.path, i.comment.kind, i.comment.start_line) for i in s.items] == [
        ("m.py", Kind.LINE, 1),
        ("m.py", Kind.DOCSTRING, 4),
        ("m.py", Kind.TRAILING, 5),
        ("r.rs", Kind.LINE, 1),
        ("r.rs", Kind.BLOCK, 3),
    ]


def test_save_shifts_later_comments_and_revert_restores(feature):
    s = open_session(feature)
    head, doc, trailing = s.items[:3]
    s.save(head, "Return one.")
    assert feature.read("m.py").startswith("# Return one.\ndef f():\n")
    assert (doc.comment.start_line, trailing.comment.start_line) == (3, 4)
    assert doc.region_start == 3

    s.save(trailing, "first\nsecond")
    assert "    # first\n    # second\n    return 1\n" in feature.read("m.py")
    s.save(doc, "Return one.\n\nAlways.")
    assert '    """Return one.\n\n    Always.\n    """\n' in feature.read("m.py")
    assert trailing.comment.start_line == 7

    for item in (trailing, head, doc):
        s.revert(item)
    assert feature.read("m.py") == FEAT_PY
    assert all(i.status is Status.PENDING for i in s.items)
    assert s.dirty_paths() == []


def test_delete_then_revert(feature):
    s = open_session(feature)
    head, doc = s.items[:2]
    s.save(head, "")
    assert head.deleted and doc.comment.start_line == 2
    with pytest.raises(EditError):
        s.save(head, "again")
    s.revert(head)
    assert not head.deleted and feature.read("m.py") == FEAT_PY


@pytest.mark.parametrize(
    "prefix,body",
    [("sum", "a */ b"), ("Return one.", 'has """ inside')],
)
def test_invalid_edits_are_refused(feature, prefix, body):
    s = open_session(feature)
    item = by_body(s, prefix)
    before = feature.read(item.path)
    with pytest.raises(EditError):
        s.save(item, body)
    assert feature.read(item.path) == before
    assert item.status is Status.PENDING


def test_merge_with_neighbouring_comment_refused(repo):
    repo.commit("base", **{"a.py": "x = 1\n"})
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("feat", **{"a.py": "# above\nx = 1  # trailing\n"})
    s = open_session(repo)
    with pytest.raises(EditError, match="merge with the comment already there"):
        s.save(s.items[1], "two\nlines")


def test_external_modification_detected(feature):
    s = open_session(feature)
    feature.write("m.py", FEAT_PY + "# sneaky\n")
    with pytest.raises(EditError, match="outside"):
        s.save(s.items[0], "changed")


def test_partial_commit_leaves_other_work_alone(feature):
    feature.write("other.py", "# staged elsewhere\n")
    feature.git("add", "other.py")
    s = open_session(feature)
    # an unrelated unstaged change in the same file, away from the comment
    feature.write("m.py", feature.read("m.py").replace("X = 2", "X = 3"))
    s.files["m.py"] = feature.read("m.py")
    s.baseline["m.py"] = s.files["m.py"]

    head = s.items[0]
    s.save(head, "Returns one.")
    s.toggle_skip(s.items[1])
    sha = s.commit("Humanize the first comment")
    assert sha

    committed = feature.show("HEAD", "m.py")
    assert committed.startswith("# Returns one.\ndef f():") and "X = 2" in committed
    assert feature.read("m.py").startswith("# Returns one.") and "X = 3" in feature.read("m.py")
    assert feature.git("diff", "--name-only").split() == ["m.py"]
    assert feature.git("diff", "--cached", "--name-only").split() == ["other.py"]
    assert "other.py" not in feature.git("show", "--name-only", "--format=", "HEAD")
    assert head.status is Status.COMMITTED and s.items[1].status is Status.SKIPPED

    with pytest.raises(EditError, match="nothing"):
        s.commit("again")

    # revert after commit is a new, committable edit
    s.revert(head)
    assert head.status is Status.EDITED and s.dirty_paths() == ["m.py"]
    s.commit("Revert")
    assert feature.show("HEAD", "m.py").startswith("# Helper that returns one.")


def test_commit_refuses_staged_changes_in_edited_file(feature):
    s = open_session(feature)
    s.save(s.items[0], "Changed.")
    feature.git("add", "m.py")
    with pytest.raises(EditError, match="staged"):
        s.commit("msg")


def test_commit_author_and_rust(feature):
    s = open_session(feature, author="Someone <someone@example.com>")
    s.save(by_body(s, "sum"), "the sum\nof both")
    s.commit("Rust comment")
    assert feature.git("log", "-1", "--format=%an <%ae>").strip() == "Someone <someone@example.com>"
    assert "    /* the sum\n     * of both\n     */\n" in feature.show("HEAD", "r.rs")


def test_last_commit_list_is_stable_after_partial_commit(feature):
    s = open_session(feature, last_commit=True)
    before = [(i.id, i.path) for i in s.items]
    s.save(s.items[0], "One.")
    s.commit("partial")
    again = open_session(feature, last_commit=True)
    # HEAD moved: a fresh session sees only the latest commit
    assert len(again.items) == 1
    assert [(i.id, i.path) for i in s.items] == before
    assert s.items[0].status is Status.COMMITTED and s.items[1].status is Status.PENDING


def test_crlf_file(repo):
    repo.commit("base", **{"a.py": "x = 1\r\n"})
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("feat", **{"a.py": "# old\r\nx = 1\r\n"})
    s = open_session(repo)
    s.save(s.items[0], "new\nlines")
    assert repo.read("a.py") == "# new\r\n# lines\r\nx = 1\r\n"
    s.commit("crlf")
    assert repo.git("status", "--porcelain") == ""


def test_blank_edges_saved_as_typed(repo):
    repo.commit("base", **{"a.py": "x = 1\n"})
    repo.git("checkout", "-q", "-b", "feature")
    src = '"""\n\nDoc.\n\n"""\n# note\nx = 1\n'
    repo.commit("feat", **{"a.py": src})
    s = open_session(repo)
    doc, note = s.items
    assert doc.comment.body == "\nDoc.\n"
    s.save(doc, doc.comment.body)  # unchanged: nothing written
    assert repo.read("a.py") == src and doc.status is Status.PENDING
    s.save(doc, "Doc.")  # dropping the blank edges is an edit like any other
    assert repo.read("a.py").startswith('"""\nDoc.\n"""\n')
    s.save(note, "note\n")
    assert repo.read("a.py").endswith("# note\n#\nx = 1\n")
    s.save(note, " \n\n")  # whitespace only still deletes
    assert note.deleted and repo.read("a.py").endswith('"""\nx = 1\n')


def test_delete_each_kind_and_revert(feature):
    s = open_session(feature)
    head, doc, trailing, rs_doc, rs_block = s.items
    for item in (trailing, doc, head, rs_block, rs_doc):
        s.delete(item)
        assert item.deleted and item.status is Status.EDITED
    assert feature.read("m.py") == "def f():\n    return 1\n\n\n# Unrelated old comment\nX = 2\n"
    assert feature.read("r.rs") == "fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n"
    with pytest.raises(EditError, match="revert it first"):
        s.delete(head)
    for item in s.items:
        s.revert(item)
    assert feature.read("m.py") == FEAT_PY and feature.read("r.rs") == FEAT_RS
    assert all(i.status is Status.PENDING and not i.deleted for i in s.items)


def test_delete_only_docstring_refused(repo):
    repo.commit("base", **{"a.py": "x = 1\n"})
    repo.git("checkout", "-q", "-b", "feature")
    src = 'class C:\n    """Only this."""\n'
    repo.commit("feat", **{"a.py": src})
    s = open_session(repo)
    with pytest.raises(EditError, match="only statement"):
        s.delete(s.items[0])
    assert repo.read("a.py") == src and not s.items[0].deleted
