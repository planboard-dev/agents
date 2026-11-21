#!/usr/bin/env python3
#
# Tests article.py: the canonical form, the addresses fetch refuses, the
# markdown cleanup, the thin-content verdict and the metadata read from
# trafilatura's JSON. Nothing here uses the network or looks up a name.
# Run with: python3 article_test.py

import contextlib
import datetime
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import article

BASE = "https://example.com/posts/two/"
TODAY = datetime.date(2026, 9, 23)


class Canonical(unittest.TestCase):
    def test_tracking_and_fragment(self):
        got = article.canonical("https://example.com/a?utm_source=x&id=7&UTM_Medium=y&fbclid=1&ref_src=twsrc#top")
        self.assertEqual(got, "https://example.com/a?id=7")

    def test_ref_kept(self):
        got = article.canonical("https://gitlab.com/g/p/-/raw/x?ref=main&utm_source=x")
        self.assertEqual(got, "https://gitlab.com/g/p/-/raw/x?ref=main")

    def test_unsafe_characters_encoded(self):
        got = article.canonical("https://example.com/a b/'$(id)'/\"x\"?q=a b&r=`id`")
        self.assertEqual(got, "https://example.com/a%20b/%27$(id)%27/%22x%22?q=a%20b&r=%60id%60")
        self.assertEqual(article.canonical(got), got)

    def test_all_parameters_removed(self):
        self.assertEqual(article.canonical("https://example.com/a?utm_source=x"), "https://example.com/a")

    def test_order_kept(self):
        self.assertEqual(article.canonical("https://example.com/a?b=2&a=1"), "https://example.com/a?b=2&a=1")

    def test_scheme_host_port(self):
        self.assertEqual(article.canonical("HTTPS://Example.COM.:443"), "https://example.com/")
        self.assertEqual(article.canonical("http://example.com:80/x"), "http://example.com/x")
        self.assertEqual(article.canonical("http://example.com:8080/x"), "http://example.com:8080/x")

    def test_path_kept(self):
        self.assertEqual(article.canonical("https://www.example.com/A/b/"), "https://www.example.com/A/b/")
        self.assertEqual(article.canonical("https://example.com/a%20b"), "https://example.com/a%20b")

    def test_ipv6(self):
        self.assertEqual(article.canonical("http://[2001:db8::1]:8080/"), "http://[2001:db8::1]:8080/")

    def test_refused(self):
        for url in ("file:///etc/passwd", "ftp://example.com/", "https://user:pw@example.com/", "https:///x", "http://example.com:99999/"):
            with self.assertRaises(article.Refused, msg=url):
                article.canonical(url)


class Check(unittest.TestCase):
    def test_refused(self):
        for url in (
            "http://localhost/",
            "http://app.localhost:3000/",
            "http://127.0.0.1/",
            "http://10.1.2.3/",
            "http://192.168.0.1/",
            "http://172.16.0.1/",
            "http://169.254.169.254/latest/",
            "http://[::1]/",
            "http://[fe80::1]/",
            "http://[::ffff:127.0.0.1]/",
            "http://0.0.0.0/",
            "file:///etc/passwd",
        ):
            with self.assertRaises(article.Refused, msg=url):
                article.check(url)

    def test_ipv6_carrying_ipv4_refused(self):
        for address in (
            "::127.0.0.1",
            "::ffff:0:127.0.0.1",
            "::ffff:0:10.0.0.1",
            "64:ff9b::127.0.0.1",
            "64:ff9b::192.168.1.1",
            "64:ff9b:1::5db8:d70e",
            "2002:7f00:1::1",
            "2002:c0a8:101::1",
            "2001:0:4136:e378:8000:63bf:3fff:fdd2",
        ):
            with self.assertRaises(article.Refused, msg=address):
                article.check("http://[%s]/" % address)

    def test_public_literal(self):
        article.check("https://93.184.215.14/")
        article.check("https://[2606:2800:21f:cb07:6820:80da:af6b:8b2c]/")
        article.check("https://[2002:5db8:d70e::1]/")
        article.check("https://[64:ff9b::5db8:d70e]/")

    def test_redirect_checked(self):
        handler = article.CheckedRedirects()
        with self.assertRaises(article.Refused):
            handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/admin")


class Base(unittest.TestCase):
    def test_base_href(self):
        body = b'<html><head><base href="/docs/"></head><body></body></html>'
        self.assertEqual(article.page_base("https://example.com/a/b", body), "https://example.com/docs/")

    def test_no_base(self):
        self.assertEqual(article.page_base("https://example.com/a/b", b"<p>x</p>"), "https://example.com/a/b")

    def test_base_not_web(self):
        body = b'<base href="javascript:alert(1)">'
        self.assertEqual(article.page_base("https://example.com/a", body), "https://example.com/a")


class Title(unittest.TestCase):
    def test_og_title_first(self):
        body = b'<head><title>Site | Post</title><meta property="og:title" content=" The  Post "></head>'
        self.assertEqual(article.page_title(body), "The Post")

    def test_title(self):
        body = b"<head><title>\n  A &amp; B\n</title></head><body><title>Later</title></body>"
        self.assertEqual(article.page_title(body), "A & B")

    def test_none(self):
        self.assertEqual(article.page_title(b"<p>x</p>"), "")
        self.assertEqual(article.page_title(b""), "")


class Files(unittest.TestCase):
    """The commands pass page-derived values in files under <dir>."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, data):
        with open(os.path.join(self.dir, name), "wb") as f:
            f.write(data)

    def text(self, name):
        with open(os.path.join(self.dir, name), encoding="utf-8") as f:
            return f.read()

    def test_fetch_writes_files(self):
        def fake(url, out):
            with open(out, "wb") as f:
                f.write(b"<p>x</p>")
            return "https://example.com/a?utm_source=x", "https://example.com/$(id)/", "https://example.com/a"

        saved = article.fetch
        article.fetch = fake
        try:
            self.assertEqual(article.fetch_into("https://example.com/a", self.dir), "https://example.com/a")
        finally:
            article.fetch = saved
        self.assertEqual(self.text("final.txt"), "https://example.com/a?utm_source=x\n")
        self.assertEqual(self.text("base.txt"), "https://example.com/$(id)/\n")
        self.assertEqual(self.text("canonical.txt"), "https://example.com/a\n")

    def test_fetch_refused_by_site(self):
        self.put("page.html", b"stale")
        self.put("article.json", b"{}")

        def fake(url, out):
            raise article.HTTPStatus(403)

        saved = article.fetch
        article.fetch = fake
        try:
            with self.assertRaises(article.HTTPStatus):
                article.fetch_into("https://example.com/a?utm_source=x#f", self.dir)
        finally:
            article.fetch = saved
        for name in ("page.html", "final.txt", "article.json"):
            self.assertFalse(os.path.exists(os.path.join(self.dir, name)), name)
        self.assertEqual(self.text("base.txt"), "https://example.com/a\n")
        self.assertEqual(self.text("canonical.txt"), "https://example.com/a\n")

    def test_clean_reads_base_file(self):
        self.put("base.txt", b"https://example.com/posts/two/\n")
        self.put("in.md", b"[a](../x) <b>\n")
        code = article.main(["clean", self.dir, os.path.join(self.dir, "in.md"), os.path.join(self.dir, "out.md")])
        self.assertEqual(code, 0)
        self.assertEqual(self.text("out.md"), "[a](https://example.com/posts/x) \\<b>\n")

    def test_clean_refuses_bad_base(self):
        self.put("base.txt", b"file:///etc/\n")
        self.put("in.md", b"x\n")
        with contextlib.redirect_stderr(io.StringIO()):
            code = article.main(["clean", self.dir, os.path.join(self.dir, "in.md"), os.path.join(self.dir, "out.md")])
        self.assertEqual(code, 2)

    def test_meta_title_from_page(self):
        self.put("page.html", b"<title>Bluesky (@bsky.app)</title>")
        self.put("article.json", json.dumps({"title": None, "text": "a b"}).encode())
        got = article.meta(self.text("article.json"), TODAY, article.page_title(b"<title>Bluesky (@bsky.app)</title>"))
        self.assertEqual(got[0], "title: Bluesky (@bsky.app)")

    def test_meta_without_json(self):
        self.put("page.html", b"<title>Only a title</title>")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = article.main(["meta", self.dir])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "title: Only a title\nwords: 0\nverdict: empty\n")


class Clean(unittest.TestCase):
    def clean(self, text):
        return article.clean(text, BASE)

    def test_relative_links_and_images(self):
        text = "See [a](/x) and [b](../three/) and [c](#sec) and ![i](img/c.png) and [d](//cdn.example.org/y).\n"
        want = (
            "See [a](https://example.com/x) and [b](https://example.com/posts/three/) and "
            "[c](https://example.com/posts/two/#sec) and ![i](https://example.com/posts/two/img/c.png) and "
            "[d](https://cdn.example.org/y).\n"
        )
        self.assertEqual(self.clean(text), want)

    def test_absolute_and_other_schemes_kept(self):
        text = "[a](https://other.org/x) [b](<javascript:alert(1)>) [c](mailto:me@example.com) [e]()\n"
        self.assertEqual(self.clean(text), text)

    def test_angle_destination_and_title(self):
        text = '[a](<my page.html>) [b](/x "Title")\n'
        want = '[a](<https://example.com/posts/two/my page.html>) [b](https://example.com/x "Title")\n'
        self.assertEqual(self.clean(text), want)

    def test_parentheses_in_destination(self):
        text = "[w](/wiki/Go_(language))\n"
        self.assertEqual(self.clean(text), "[w](https://example.com/wiki/Go_(language))\n")

    def test_linked_image(self):
        text = "[![alt](/i.png)](/big.png)\n"
        self.assertEqual(self.clean(text), "[![alt](https://example.com/i.png)](https://example.com/big.png)\n")

    def test_raw_html_escaped(self):
        text = "Text <script>alert(1)</script> and a <div> and <!-- c --> and <?php and 1 < 2 and <https://x.org> and <me@x.org>.\n"
        want = "Text \\<script>alert(1)\\</script> and a \\<div> and \\<!-- c --> and \\<?php and 1 < 2 and <https://x.org> and <me@x.org>.\n"
        self.assertEqual(self.clean(text), want)

    def test_already_escaped(self):
        text = "An \\<em> tag.\n"
        self.assertEqual(self.clean(text), text)

    def test_code_untouched(self):
        text = "Use `<div>` and `[a](/x)` and ``a ` <b>`` here <i>.\n\n```\n<string> [a](/x)\n    indented\n```\n"
        want = "Use `<div>` and `[a](/x)` and ``a ` <b>`` here \\<i>.\n\n```\n<string> [a](/x)\n    indented\n```\n"
        self.assertEqual(self.clean(text), want)

    def test_indented_paragraph_unindented(self):
        text = "# [Blog](https://go.dev/blog/)\n\n    \n    # Title\n\n        **Next:** [x](/n)\n        more\n"
        want = "# [Blog](https://go.dev/blog/)\n\n\n# Title\n\n**Next:** [x](https://example.com/n)\n        more\n"
        self.assertEqual(self.clean(text), want)

    def test_first_line_unindented(self):
        self.assertEqual(self.clean("    *Quoted text.*\n"), "*Quoted text.*\n")

    def test_continuation_kept(self):
        text = "A paragraph\n      continues here\n      - not a list\n"
        self.assertEqual(self.clean(text), text)

    def test_list_content_kept(self):
        text = "- item\n\n    more of the item\n\nAfter.\n\n    Code start.\n"
        want = "- item\n\n    more of the item\n\nAfter.\n\nCode start.\n"
        self.assertEqual(self.clean(text), want)

    def test_nested_list_kept(self):
        text = "- outer\n  - inner\n    - deeper\n"
        self.assertEqual(self.clean(text), text)

    def test_table_kept(self):
        text = "| A | B | \n|---|---|\n| [x](/x) | 2 | \n"
        self.assertEqual(self.clean(text), "| A | B | \n|---|---|\n| [x](https://example.com/x) | 2 | \n")

    def test_idempotent(self):
        text = "    Para <b> [a](/x).\n\n```\n<c>\n```\n"
        once = self.clean(text)
        self.assertEqual(self.clean(once), once)


class Words(unittest.TestCase):
    def test_count(self):
        text = "# Title\n\nOne [two](https://example.com/very/long) three <https://x.org> https://y.org four - | ---\n"
        self.assertEqual(article.count_words(text), 5)

    def test_verdict(self):
        self.assertEqual(article.verdict("", 0), "empty")
        self.assertEqual(article.verdict("x", 149), "thin")
        self.assertEqual(article.verdict("x", 150), "ok")
        notice = "This is a heavily interactive web application, and JavaScript is required."
        self.assertEqual(article.verdict(notice, 399), "thin")
        self.assertEqual(article.verdict(notice, 400), "ok")
        self.assertEqual(article.verdict("Please enable JavaScript to continue", 200), "thin")
        self.assertEqual(article.verdict("A book on JavaScript engines", 200), "ok")


class Meta(unittest.TestCase):
    def meta(self, **doc):
        return article.meta(json.dumps(doc), TODAY)

    def test_fields(self):
        text = " ".join(["word"] * 200)
        got = self.meta(title="Faster  Go maps\n with Swiss Tables", date="2025-02-26", text=text)
        self.assertEqual(got, ["title: Faster Go maps with Swiss Tables", "published: 2025-02-26", "words: 200", "verdict: ok"])

    def test_dates_left_out(self):
        for date in ("2026-09-23", "2026-10-01", "2026-01-01", "", None, "2025-02-30", "Feb 2025"):
            got = self.meta(title="T", date=date, text="a b")
            self.assertFalse(any(line.startswith("published:") for line in got), date)

    def test_empty_output(self):
        self.assertEqual(article.meta("", TODAY), ["words: 0", "verdict: empty"])

    def test_no_title(self):
        self.assertEqual(self.meta(text="a b"), ["words: 2", "verdict: thin"])


if __name__ == "__main__":
    unittest.main()
