#!/usr/bin/env python3
#
# Tests local.py: the arguments it takes as a path, the files it refuses, the
# name and hash of the copy, the title and date it reads, and the cleanup with
# no base, which turns a relative link or image into its text.
# Run with: python3 local_test.py

import contextlib
import hashlib
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import local


class Resolve(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(local.resolve("/a/b.pdf"), "/a/b.pdf")
        self.assertEqual(local.resolve("~/b.pdf"), os.path.expanduser("~/b.pdf"))
        self.assertEqual(local.resolve("./b.pdf"), os.path.join(os.getcwd(), "b.pdf"))

    def test_file_urls(self):
        self.assertEqual(local.resolve("file:///a/my%20paper.pdf"), "/a/my paper.pdf")
        self.assertEqual(local.resolve("FILE://localhost/a/b.pdf"), "/a/b.pdf")

    def test_refused(self):
        for argument in (
            "paper.pdf",
            "~other/b.pdf",
            "https://example.com/b.pdf",
            "file://server/share/b.pdf",
            "file:///a/b.pdf?x=1",
            "file:///a/b.pdf#page=2",
            "file:b.pdf",
        ):
            with self.subTest(argument=argument):
                with self.assertRaises(local.Refused):
                    local.resolve(argument)


class PlainName(unittest.TestCase):
    def test_names(self):
        cases = {
            "/x/Attention Is All You Need.PDF": "Attention-Is-All-You-Need.pdf",
            "/x/notes_v2.md": "notes_v2.md",
            "/x/.hidden.html": "hidden.html",
            "/x/$(id)`x`'q'.htm": "id-x-q.htm",
            "/x/-..-.pdf": "original.pdf",
            "/x/%s.pdf" % ("a" * 150): "%s.pdf" % ("a" * 100),
            "/x/caf\u00e9 menu.markdown": "caf-menu.markdown",
        }
        for path, want in cases.items():
            with self.subTest(path=path):
                self.assertEqual(local.plain_name(path), want)


class Copy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "src")
        self.work = os.path.join(self.tmp.name, "work")
        os.makedirs(self.src)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, data):
        path = os.path.join(self.src, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_copies_and_hashes(self):
        data = b"%PDF-1.7\nbody"
        path = self.put("My Paper.pdf", data)
        kind, name, canonical = local.copy_into(path, self.work)
        self.assertEqual((kind, name), ("pdf", "My-Paper.pdf"))
        self.assertEqual(canonical, "local:sha256:" + hashlib.sha256(data).hexdigest())
        with open(os.path.join(self.work, "raw", name), "rb") as f:
            self.assertEqual(f.read(), data)

    def test_symlink_resolved(self):
        target = self.put("notes.md", b"# Notes\n")
        link = os.path.join(self.src, "link")
        os.symlink(target, link)
        kind, name, _ = local.copy_into(link, self.work)
        self.assertEqual((kind, name), ("markdown", "notes.md"))

    def test_stale_removed(self):
        os.makedirs(os.path.join(self.work, "raw"))
        with open(os.path.join(self.work, "raw", "old.pdf"), "wb") as f:
            f.write(b"old")
        with open(os.path.join(self.work, "pdfinfo.txt"), "w") as f:
            f.write("Title: old\n")
        local.copy_into(self.put("new.md", b"x"), self.work)
        self.assertEqual(os.listdir(os.path.join(self.work, "raw")), ["new.md"])
        self.assertFalse(os.path.exists(os.path.join(self.work, "pdfinfo.txt")))

    def test_refused(self):
        self.put("paper.docx", b"x")
        self.put("fake.pdf", b"<html>not a pdf</html>")
        cases = [
            os.path.join(self.src, "missing.pdf"),
            self.src,
            os.path.join(self.src, "paper.docx"),
            os.path.join(self.src, "fake.pdf"),
            "/dev/null",
        ]
        for argument in cases:
            with self.subTest(argument=argument):
                with self.assertRaises(local.Refused):
                    local.copy_into(argument, self.work)

    def test_main_refusal_exit(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = local.main(["copy", "paper.pdf", self.work])
        self.assertEqual(code, 2)
        self.assertTrue(err.getvalue().startswith("refused: "))


class Meta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = self.tmp.name
        os.makedirs(os.path.join(self.work, "raw"))

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, text):
        with open(os.path.join(self.work, name), "w", encoding="utf-8") as f:
            f.write(text)

    def test_pdf(self):
        self.put("raw/a-paper.pdf", "%PDF-")
        self.put("pdfinfo.txt", "Title:          A  Paper: On Things\nCreationDate:   2017-06-12T10:00:00+02:00\nPages:          9\n")
        self.assertEqual(local.meta(self.work), ["title: A Paper: On Things", "published: 2017-06-12"])

    def test_pdf_without_info(self):
        self.put("raw/a-paper_v2.pdf", "%PDF-")
        self.put("pdfinfo.txt", "Title:          \nCreationDate:   D:2017\n")
        self.assertEqual(local.meta(self.work), ["title: a paper v2"])

    def test_markdown_front_matter(self):
        self.put("raw/notes.md", '---\ntitle: "Front Title"\n---\n\n# Heading\n')
        self.put("converted.md", "# Heading\n")
        self.assertEqual(local.meta(self.work), ["title: Front Title"])

    def test_markdown_heading(self):
        self.put("raw/notes.md", "```\n# not this\n```\n\n# The *Heading* #\n")
        self.put("converted.md", "```\n# not this\n```\n\n# The *Heading*\n")
        self.assertEqual(local.meta(self.work), ["title: The *Heading*"])

    def test_html_title(self):
        self.put("raw/page.html", "<html><head><title> A\n page </title></head><body><h1>H</h1></body></html>")
        self.put("converted.md", "# H\n")
        self.assertEqual(local.meta(self.work), ["title: A page"])

    def test_html_without_title(self):
        self.put("raw/saved_page.htm", "<p>x</p>")
        self.put("converted.md", "x\n")
        self.assertEqual(local.meta(self.work), ["title: saved page"])


class Clean(unittest.TestCase):
    def clean(self, text):
        return local.article.clean(text, None)

    def test_relative_made_text(self):
        text = 'See [a](other.md) and ![pic](img/c.png "t") and [b](/abs/x) and [c](<my file.html>) and [d](//cdn.example.org/y).\n'
        want = "See a and pic and b and c and d.\n"
        self.assertEqual(self.clean(text), want)

    def test_others_kept(self):
        text = "[a](https://x.org/y) [b](#sec) [c](mailto:me@example.com) [e]() and 1 < 2\n"
        self.assertEqual(self.clean(text), text)

    def test_nested(self):
        self.assertEqual(self.clean("[![alt](i.png)](big.png)\n"), "alt\n")
        self.assertEqual(self.clean("[![alt](i.png)](https://x.org/)\n"), "[alt](https://x.org/)\n")
        self.assertEqual(self.clean("[a [b] c](x.md)\n"), "a [b] c\n")

    def test_escaped_brackets(self):
        self.assertEqual(self.clean("\\[not [link](x.md)\n"), "\\[not link\n")
        self.assertEqual(self.clean("\\![a](x.png)\n"), "\\!a\n")

    def test_space_before_destination(self):
        self.assertEqual(self.clean("[a]( /api/projects) ![i](\t<x.png> \"t\")\n"), "a i\n")
        self.assertEqual(self.clean("[a]( https://x.org/)\n"), "[a]( https://x.org/)\n")

    def test_destination_on_next_line(self):
        self.assertEqual(self.clean("See [a](\n  /x) and ![i](\n<y.png>).\n"), "See a and i.\n")
        self.assertEqual(self.clean("```\n[a](\n/x)\n```\n"), "```\n[a](\n/x)\n```\n")

    def test_reference_definitions(self):
        text = (
            "[a][r] [b][] [c] ![d][r]\n\n"
            "[r]: /api/projects\n"
            "[b]: <other page.md> \"t\"\n"
            "> - [c]:\n"
            ">   c.md\n"
            "[w]: https://x.org/\n"
            "[^1]: A footnote.\n"
        )
        want = (
            "[a][r] [b][] [c] ![d][r]\n\n"
            "\\[r]: /api/projects\n"
            "\\[b]: \\<other page.md> \"t\"\n"
            "> - \\[c]:\n"
            ">   c.md\n"
            "[w]: https://x.org/\n"
            "[^1]: A footnote.\n"
        )
        self.assertEqual(self.clean(text), want)
        self.assertEqual(self.clean(want), want)

    def test_opener_out_of_reach(self):
        self.assertEqual(self.clean("[see `code`](x.md)\n"), "[see `code`](<>)\n")

    def test_raw_html_escaped(self):
        self.assertEqual(self.clean("<script>alert(1)</script>\n"), "\\<script>alert(1)\\</script>\n")

    def test_code_untouched(self):
        text = "Use `[a](x.md)`.\n\n```\n[a](x.md)\n```\n"
        self.assertEqual(self.clean(text), text)

    def test_idempotent(self):
        once = self.clean("[a](x.md) [see `c`](y.md) <b>\n")
        self.assertEqual(self.clean(once), once)

    def test_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.md")
            out = os.path.join(tmp, "out.md")
            with open(src, "w") as f:
                f.write("[a](x.md) <b>\n")
            self.assertEqual(local.main(["clean", src, out]), 0)
            with open(out) as f:
                self.assertEqual(f.read(), "a \\<b>\n")


if __name__ == "__main__":
    unittest.main()
