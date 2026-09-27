from comment_humanizer.gitdiff import EMPTY_TREE, added_lines, parse_diff, resolve_base


def test_parse_diff():
    diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,0 +2,3 @@ ctx
+x
@@ -9 +12 @@
-y
+z
@@ -20,2 +22,0 @@
-gone
diff --git a/old.rs b/old.rs
--- a/old.rs
+++ /dev/null
@@ -1 +0,0 @@
-x
"""
    assert parse_diff(diff) == {"a.py": {2, 3, 4, 12}}


def test_branch_mode(repo):
    repo.commit("base", **{"a.py": "x = 1\n", "b.rs": "fn f() {}\n"})
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("feat", **{"a.py": "# new\nx = 1\n", "src__c.rs": "// c\n"})
    repo.git("checkout", "-q", "master")
    master_sha = repo.commit("master moves", **{"b.rs": "// on master\nfn f() {}\n"})
    repo.git("checkout", "-q", "feature")

    base = resolve_base(str(repo.root))
    assert base != master_sha
    repo.write("untracked.py", "# u\n")
    repo.write("ignored.txt", "# no\n")
    assert added_lines(str(repo.root), base) == {"a.py": {1}, "src/c.rs": {1}, "untracked.py": {1, 2}}
    assert added_lines(str(repo.root), base, ["src"]) == {"src/c.rs": {1}}


def test_last_commit_mode(repo):
    repo.commit("one", **{"a.py": "x = 1\n"})
    assert resolve_base(str(repo.root), last_commit=True) == EMPTY_TREE
    first = repo.git("rev-parse", "HEAD").strip()
    repo.commit("two", **{"a.py": "x = 1\n# two\n"})
    base = resolve_base(str(repo.root), last_commit=True)
    assert base == first
    assert added_lines(str(repo.root), base) == {"a.py": {2}}


def test_explicit_base_falls_back_to_main(repo):
    repo.git("checkout", "-q", "-b", "main")
    sha = repo.commit("one", **{"a.py": "x = 1\n"})
    repo.git("checkout", "-q", "-b", "topic")
    repo.commit("two", **{"a.py": "x = 2\n"})
    assert resolve_base(str(repo.root)) == sha
    assert resolve_base(str(repo.root), base="main") == sha
