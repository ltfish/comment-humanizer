from comment_humanizer.extract import extract_rust
from comment_humanizer.models import Kind


def summary(src):
    return [(c.kind, c.marker, c.start_line, c.end_line, c.body) for c in extract_rust(src, "t.rs")]


def test_line_markers_group_separately():
    src = "//! crate\n/// doc a\n/// doc b\n// plain\nfn f() {}\n//// four\n"
    assert summary(src) == [
        (Kind.LINE, "//!", 1, 1, "crate"),
        (Kind.LINE, "///", 2, 3, "doc a\ndoc b"),
        (Kind.LINE, "//", 4, 4, "plain"),
        (Kind.LINE, "//", 6, 6, "// four"),
    ]


def test_trailing_comment():
    (c,) = extract_rust("    let x = 1; // one\n", "t.rs")
    assert c.kind is Kind.TRAILING and c.indent == "    " and c.start_col == 15 and c.body == "one"


def test_strings_are_not_comments():
    src = r"""let a = "// no \" /* no";
let b = r#"/* "no" */"#;
let c = br"//";
let d = b"/*";
let e = c"//";
"""
    assert extract_rust(src, "t.rs") == []


def test_char_literals_and_lifetimes():
    src = "fn f<'a>(x: &'a str) { let q = '\"'; let s = '\\''; let b = b'/'; let u = '\\u{2F}'; } // end\n"
    assert summary(src) == [(Kind.TRAILING, "//", 1, 1, "end")]


def test_label_and_raw_identifier():
    src = "'outer: loop { let r#type = 1; break 'outer; } // ok\n"
    assert [c.body for c in extract_rust(src, "t.rs")] == ["ok"]


def test_nested_block():
    (c,) = extract_rust("/* a /* b */ c */ fn f() {}\n", "t.rs")
    assert c.kind is Kind.BLOCK and c.body == "a /* b */ c" and c.end_col == 17


def test_star_block():
    src = "    /**\n     * First.\n     *\n     * Second.\n     */\n"
    (c,) = extract_rust(src, "t.rs")
    assert c.marker == "/**" and c.body == "First.\n\nSecond."
    assert c.delim is not None and c.delim.cont_prefix == "     * " and c.delim.close_prefix == "     "


def test_plain_multiline_block():
    src = "/* first\n   second\n   third */\n"
    (c,) = extract_rust(src, "t.rs")
    assert c.body == "first\nsecond\nthird"
    assert c.delim is not None and not c.delim.closing_own_line and c.delim.cont_prefix == "   "


def test_block_markers():
    assert [c.marker for c in extract_rust("/*! a */\n/** b */\n/*** c */\n/**/\n", "t.rs")] == [
        "/*!",
        "/**",
        "/*",
        "/*",
    ]


def test_unterminated_block_ignored():
    assert summary("// ok\n/* never closed\n") == [(Kind.LINE, "//", 1, 1, "ok")]
