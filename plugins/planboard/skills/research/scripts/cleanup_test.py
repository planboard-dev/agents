#!/usr/bin/env python3
#
# Tests cleanup.py: one small fixture per transformation, the shapes it must
# leave alone, and, when CLEANUP_SAMPLES names a directory of real arxiv2md
# output (any */source.md below it), a check that each keeps its headings and
# References section. CLEANUP_PAGES does the same for the figure pass over
# arXiv's saved pages. Run with: python3 cleanup_test.py

import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cleanup


class Abstract(unittest.TestCase):
    def test_doubled_word(self):
        got = cleanup.clean("## Abstract\n\nAbstract The dominant models.\n")
        self.assertEqual(got, "## Abstract\n\nThe dominant models.\n")

    def test_word_not_doubled(self):
        text = "## Abstract\n\nAbstract interpretation is a theory.\n"
        self.assertEqual(cleanup.clean(text), text)

    def test_word_outside_abstract(self):
        text = "## 1 Introduction\n\nAbstract The dominant models.\n"
        self.assertEqual(cleanup.clean(text), text)

    def test_doubled_math(self):
        text = (
            "## Abstract\n\n"
            "Abstract Across seven models ( 1,323 1{,}323 episodes), up to 59 % 59\\% ); "
            "Decay is 8.3 \u00d7 8.3\\times larger, the probe ( 0 % \u2192 65 % 0\\%{\\to}65\\% ), "
            "for \u2248 \\approx 47 tokens ( < 0.5 % <\\!0.5\\% of it), from 0% to 30%.\n\n"
            "## 1 Introduction\n\nKept 59 % 59\\% here.\n"
        )
        want = (
            "## Abstract\n\n"
            "Across seven models ( $1{,}323$ episodes), up to $59\\%$ ); "
            "Decay is $8.3\\times$ larger, the probe ( $0\\%{\\to}65\\%$ ), "
            "for $\\approx$ 47 tokens ( $<\\!0.5\\%$ of it), from 0% to 30%.\n\n"
            "## 1 Introduction\n\nKept 59 % 59\\% here.\n"
        )
        self.assertEqual(cleanup.clean(text), want)

    def test_math_left_when_abstract_has_dollars(self):
        text = "## Abstract\n\nUp to 59 % 59\\% and $x$.\n"
        self.assertEqual(cleanup.clean(text), text)

    def test_math_left_when_copies_differ(self):
        text = "## Abstract\n\nUp to 58 % 59\\% and 3 \\alpha here.\n"
        self.assertEqual(cleanup.clean(text), text)


class Bullets(unittest.TestCase):
    def test_bullet_on_own_line(self):
        text = "Three ways:\n\n- \u2022\nFirst one.\n- \u2022\nSecond one.\n"
        self.assertEqual(cleanup.clean(text), "Three ways:\n\n- First one.\n- Second one.\n")

    def test_bullet_inline(self):
        self.assertEqual(cleanup.clean("- \u2022 First one.\n"), "- First one.\n")

    def test_bullet_with_nothing_after(self):
        text = "- \u2022\n\nNext paragraph.\n"
        self.assertEqual(cleanup.clean(text), text)

    def test_bullet_before_a_block(self):
        for after in ("## 2 Next", "- item", "1. item", "```", "$$ $a$ $$", "$$", "| a | b |", "> quote", "- \u2022"):
            text = "- \u2022\n" + after + "\n"
            with self.subTest(after=after):
                self.assertTrue(cleanup.clean(text).startswith("- \u2022\n"))

    def test_consecutive_bullets_idempotent(self):
        text = "- \u2022\n- \u2022\nText.\n"
        once = cleanup.clean(text)
        self.assertEqual(once, "- \u2022\n- Text.\n")
        self.assertEqual(cleanup.clean(once), once)


class Footnotes(unittest.TestCase):
    def test_footnote(self):
        text = (
            "Small gradients (^1^1 1 To illustrate, $q\\cdot k$ has mean $0$.). To counteract.\n"
            "\n"
            "Each GPU (^2^2 2 We used values of 2.8 (K80).).\n"
        )
        want = (
            "Small gradients[^1]. To counteract.\n"
            "\n"
            "Each GPU[^2].\n"
            "\n"
            "[^1]: To illustrate, $q\\cdot k$ has mean $0$.\n"
            "[^2]: We used values of 2.8 (K80).\n"
        )
        self.assertEqual(cleanup.clean(text), want)

    def test_unclosed_footnote(self):
        text = "Small gradients (^1^1 1 To illustrate\nthe rest.)\n"
        self.assertEqual(cleanup.clean(text), text)

    def test_paren_inside_math(self):
        text = "Values (^1^1 1 on $[0,1)$ and $$f(x$$ here.) end.\n"
        want = "Values[^1] end.\n\n[^1]: on $[0,1)$ and $$f(x$$ here.\n"
        self.assertEqual(cleanup.clean(text), want)

    def test_uncertain_balance(self):
        for text in ("Values (^1^1 1 on $[0,1) here.) end.\n", "Values (^1^1 1 on \\) here.) end.\n"):
            self.assertEqual(cleanup.clean(text), text)

    def test_mismatched_numbers(self):
        text = "Small gradients (^1^2 1 To illustrate.).\n"
        self.assertEqual(cleanup.clean(text), text)

    def test_number_already_used(self):
        text = "Small gradients (^1^1 1 To illustrate.).\n\n[^1]: Existing.\n"
        self.assertEqual(cleanup.clean(text), text)


class Display(unittest.TestCase):
    def test_numbered(self):
        text = "$$ $\\mathrm{FFN}(x)=\\max(0,xW_{1})$ (2) $$\n"
        self.assertEqual(cleanup.clean(text), "$$\n\\mathrm{FFN}(x)=\\max(0,xW_{1}) \\tag{2}\n$$\n")

    def test_unnumbered(self):
        self.assertEqual(cleanup.clean("$$ $a=b,$ $$\n"), "$$\na=b,\n$$\n")

    def test_aligned(self):
        text = (
            "$$ $\\displaystyle\\mathrm{MultiHead}(Q)$ $\\displaystyle=\\mathrm{Concat}(h)$ "
            "$\\displaystyle\\text{where}~h$ $\\displaystyle=\\mathrm{Attention}(Q)$ $$\n"
        )
        want = (
            "$$\n\\begin{aligned}\n"
            "\\mathrm{MultiHead}(Q) &=\\mathrm{Concat}(h) \\\\\n"
            "\\text{where}~h &=\\mathrm{Attention}(Q)\n"
            "\\end{aligned}\n$$\n"
        )
        self.assertEqual(cleanup.clean(text), want)

    def test_rows(self):
        text = "$$ $\\displaystyle PE_{1}=sin(x)$ $\\displaystyle PE_{2}=cos(x)$ (4) $$\n"
        want = "$$\n\\begin{aligned}\nPE_{1}=sin(x) \\\\\nPE_{2}=cos(x)\n\\end{aligned} \\tag{4}\n$$\n"
        self.assertEqual(cleanup.clean(text), want)

    def test_mixed_fragments(self):
        text = "$$ $a$ $\\displaystyle=b$ $$\n"
        self.assertEqual(cleanup.clean(text), text)

    def test_indented(self):
        text = "- item\n\n  $$ $a=b$ (1) $$\n"
        self.assertEqual(cleanup.clean(text), "- item\n\n  $$\n  a=b \\tag{1}\n  $$\n")

    def test_other_shapes(self):
        for text in ("$$ a=b $$\n", "$$\na=b\n$$\n", "Inline $$ $a$ $$ here.\n", "$$ $a$ (1) (2) $$\n"):
            self.assertEqual(cleanup.clean(text), text)


class Figures(unittest.TestCase):
    def test_figure(self):
        text = (
            "Figure: Figure 1: The *same* model, $\\pi$ [b.\n"
            "Refer to caption: https://arxiv.org/html/x/a.png\n"
            "\n"
            "Next.\n"
        )
        want = (
            "![Figure 1](https://arxiv.org/html/x/a.png)\n"
            "\n"
            "Figure 1: The *same* model, $\\pi$ [b.\n"
            "\n"
            "Next.\n"
        )
        self.assertEqual(cleanup.clean(text), want)

    def test_figure_without_label(self):
        text = "Figure: The model.\nRefer to caption: https://arxiv.org/html/x/a.png\n"
        self.assertEqual(cleanup.clean(text), "![Figure](https://arxiv.org/html/x/a.png)\n\nThe model.\n")

    def test_caption_ending_in_backslash(self):
        text = "Figure: Figure 2: Ends in \\\nRefer to caption: https://e.com/a.png\nNext.\n"
        want = "![Figure 2](https://e.com/a.png)\n\nFigure 2: Ends in \\\n\nNext.\n"
        self.assertEqual(cleanup.clean(text), want)

    def test_figure_without_url(self):
        text = "Figure: Figure 3: No image here.\n\nNext.\n"
        self.assertEqual(cleanup.clean(text), text)

    def test_figure_left_alone(self):
        for text in (
            "Figure: Figure 1: A.\nRefer to caption: http://example.com/a.png\n",
            "Figure: Figure 1: A.\nRefer to caption: https://example.com/a(1).png\n",
            "Figure: # A.\nRefer to caption: https://example.com/a.png\n",
            "Figure: Figure 1: A.\nRefer to caption: https://e.com/a.png\nRefer to caption: https://e.com/b.png\n",
        ):
            self.assertEqual(cleanup.clean(text), text)


PAGE_URL = "https://arxiv.org/html/1234.56789v2"

# One figure of each kind arXiv's page holds, one with nothing to show, and a
# table, which is ignored.
PAGE = """<html><body>
<figure id="S1.F1" class="ltx_figure"><img src="1234.56789v2/x1.png" alt="Refer to caption">
<img src="1234.56789v2/x2.png" alt="Refer to caption">
<figcaption><span class="ltx_tag ltx_tag_figure">Figure 1: </span>Plain.</figcaption></figure>
<figure id="S1.F6" class="ltx_figure"><p>Text only.</p>
<figcaption><span class="ltx_tag ltx_tag_figure">Figure 6: </span>Empty.</figcaption></figure>
<figure id="S1.T1" class="ltx_table"><object type="image/svg+xml" data="1234.56789v2/logo.svg"></object>
<img src="1234.56789v2/logo.png">
<figcaption><span class="ltx_tag ltx_tag_table">Table 1: </span>Logos.</figcaption></figure>
<figure id="S2.F2" class="ltx_figure">
<object type="image/svg+xml" data="1234.56789v2/a.svg" class="ltx_figure_panel"></object>
<object type="image/svg+xml" data="1234.56789v2/b.svg" class="ltx_figure_panel"></object>
<figcaption><span class="ltx_tag ltx_tag_figure">Figure 2: </span>Hosted.</figcaption></figure>
<figure id="S3.F3" class="ltx_figure"><svg><g><foreignObject>
<img src="1234.56789v2/logos/logo.png" alt="Refer to caption"/></foreignObject></g></svg>
<figcaption><span class="ltx_tag ltx_tag_figure">Figure 3<span>:</span> </span>Drawn.</figcaption></figure>
</body></html>
"""


def page(html=PAGE):
    return cleanup.page_figures(html, PAGE_URL)


class PageFigures(unittest.TestCase):
    def test_kinds(self):
        got = page()
        self.assertEqual(
            got,
            {
                "1": (
                    cleanup.HOSTED,
                    ["https://arxiv.org/html/1234.56789v2/x1.png", "https://arxiv.org/html/1234.56789v2/x2.png"],
                    None,
                ),
                "2": (
                    cleanup.HOSTED,
                    ["https://arxiv.org/html/1234.56789v2/a.svg", "https://arxiv.org/html/1234.56789v2/b.svg"],
                    None,
                ),
                "3": (cleanup.DRAWING, [], PAGE_URL + "#S3.F3"),
            },
        )

    def test_duplicate_number_dropped(self):
        html = PAGE + PAGE.replace("S2.F2", "A.F2").replace("S3.F3", "A.F9").replace("Figure 3", "Figure 9")
        self.assertEqual(sorted(page(html)), ["3", "9"])

    def test_panel_outside_the_page_drops_figure(self):
        for panel in (
            "https://example.com/b.svg",
            "//example.com/b.svg",
            "https://user@arxiv.org/html/1234.56789v2/b.svg",
            "https://arxiv.org.example.com/html/1234.56789v2/b.svg",
            "https://ARXIV.org/html/1234.56789v2/b.svg",
            "https://arxiv.org:8443/html/1234.56789v2/b.svg",
            "http://arxiv.org/html/1234.56789v2/b.svg",
            "/html/1234.56789v1/b.svg",
            "/html/1234.56789v2x/b.svg",
            "/html/9999.99999v1/b.svg",
            "1234.56789v2/../../9999.99999v1/b.svg",
            "1234.56789v2/%2e%2e/b.svg",
            "1234.56789v2/b.svg?x=1",
            "1234.56789v2/b\"c.svg",
            "1234.56789v2/b]c.svg",
            "1234.56789v2/b\\c.svg",
            "1234.56789v2/b\x01c.svg",
        ):
            with self.subTest(panel=panel):
                html = PAGE.replace("1234.56789v2/b.svg", panel.replace('"', "&quot;"))
                got = page(html)
                self.assertNotIn("2", got)
                self.assertIn("1", got)

    def test_absolute_panel_on_the_page_kept(self):
        html = PAGE.replace("1234.56789v2/b.svg", "https://arxiv.org/html/1234.56789v2/b.svg")
        self.assertIn("2", page(html))

    def test_page_of_another_paper(self):
        with self.assertRaises(cleanup.PageError):
            cleanup.page_figures(PAGE, "https://arxiv.org/html/9999.99999v1")
        with self.assertRaises(cleanup.PageError):
            cleanup.page_figures(PAGE, "https://arxiv.org/html/1234.56789v1")
        # A page with no panels at all cannot be told apart, so only its
        # drawings can match.
        drawn = (
            '<figure id="S3.F3" class="ltx_figure"><svg><g></g></svg>'
            '<figcaption><span class="ltx_tag ltx_tag_figure">Figure 3: </span>Drawn.</figcaption></figure>'
        )
        got = cleanup.page_figures(drawn, "https://arxiv.org/html/9999.99999v1")
        self.assertEqual(list(got), ["3"])

    def test_bad_page_url(self):
        for url in (
            PAGE_URL + "/",
            PAGE_URL + "?x=1",
            PAGE_URL + "#S1",
            "https://arxiv.org",
            "https://arxiv.org/",
            "https://ARXIV.org/html/1234.56789v2",
            "https://arxiv.org:443/html/1234.56789v2",
            "https://u@arxiv.org/html/1234.56789v2",
            "http://arxiv.org/html/1234.56789v2",
        ):
            with self.subTest(url=url):
                self.assertIsNotNone(cleanup.page_url_error(url))
                with self.assertRaises(cleanup.PageError):
                    cleanup.page_figures(PAGE, url)
        self.assertIsNone(cleanup.page_url_error(PAGE_URL))

    def test_unsafe_panel_or_id_drops_figure(self):
        self.assertNotIn("2", page(PAGE.replace("1234.56789v2/b.svg", "b (1).svg")))
        self.assertNotIn("3", page(PAGE.replace('id="S3.F3"', 'id="S3 F3"')))

    def test_subfigure_tags_ignored(self):
        html = (
            '<figure id="S4.F4" class="ltx_figure">'
            '<figure id="S4.F4.sf1" class="ltx_figure ltx_figure_panel">'
            '<object type="image/svg+xml" data="1234.56789v2/c.svg"></object>'
            '<figcaption><span class="ltx_tag ltx_tag_figure">(a) </span>Left.</figcaption></figure>'
            '<img src="1234.56789v2/d.png">'
            '<figcaption><span class="ltx_tag ltx_tag_figure">Figure 4: </span>Both.</figcaption></figure>'
        )
        want = ["https://arxiv.org/html/1234.56789v2/c.svg", "https://arxiv.org/html/1234.56789v2/d.png"]
        self.assertEqual(page(html), {"4": (cleanup.HOSTED, want, None)})


class PageFigurePass(unittest.TestCase):
    def test_hosted_bare(self):
        text = "Before.\n\nFigure: Figure 2: Hosted $x$.\n\nNext.\n"
        want = (
            "Before.\n\n"
            "![Figure 2](https://arxiv.org/html/1234.56789v2/a.svg)\n\n"
            "![Figure 2](https://arxiv.org/html/1234.56789v2/b.svg)\n\n"
            "Figure 2: Hosted $x$.\n\nNext.\n"
        )
        got = cleanup.clean(text, page())
        self.assertEqual(got, want)
        self.assertEqual(cleanup.clean(got, page()), got)

    def test_hosted_replaces_arxiv2md_image(self):
        text = "Figure: Figure 2: Hosted.\nRefer to caption: https://arxiv.org/html/1234.56789/1234.56789v2/p.png\n"
        want = (
            "![Figure 2](https://arxiv.org/html/1234.56789v2/a.svg)\n\n"
            "![Figure 2](https://arxiv.org/html/1234.56789v2/b.svg)\n\n"
            "Figure 2: Hosted.\n"
        )
        self.assertEqual(cleanup.clean(text, page()), want)

    def test_drawing_bare(self):
        text = "Figure: Figure 3: Drawn.\nNext.\n"
        want = "Figure 3: Drawn.\n\n[Figure 3 on arXiv](https://arxiv.org/html/1234.56789v2#S3.F3)\n\nNext.\n"
        got = cleanup.clean(text, page())
        self.assertEqual(got, want)
        self.assertEqual(cleanup.clean(got, page()), got)

    def test_drawing_drops_image(self):
        want = "Figure 3: Drawn.\n\n[Figure 3 on arXiv](https://arxiv.org/html/1234.56789v2#S3.F3)\n\nNext.\n"
        raw = "Figure: Figure 3: Drawn.\nRefer to caption: https://arxiv.org/html/1234.56789/logos/logo.png\n\nNext.\n"
        cleaned = "![Figure 3](https://arxiv.org/html/1234.56789/logos/logo.png)\n\nFigure 3: Drawn.\n\nNext.\n"
        self.assertEqual(cleanup.clean(raw, page()), want)
        self.assertEqual(cleanup.clean(cleaned, page()), want)

    def test_plain_images_replace_arxiv2md_image(self):
        text = "Figure: Figure 1: Plain.\nRefer to caption: https://arxiv.org/html/1234.56789/1234.56789v2/x1.png\n\nNext.\n"
        want = (
            "![Figure 1](https://arxiv.org/html/1234.56789v2/x1.png)\n\n"
            "![Figure 1](https://arxiv.org/html/1234.56789v2/x2.png)\n\n"
            "Figure 1: Plain.\n\nNext.\n"
        )
        got = cleanup.clean(text, page())
        self.assertEqual(got, want)
        self.assertEqual(cleanup.clean(got, page()), got)

    def test_unmatched(self):
        # Figure 6 has nothing to show on the page; Figure 7 is not on it.
        text = (
            "Figure: Figure 6: Empty.\nRefer to caption: https://arxiv.org/html/x/x6.png\n\n"
            "Figure: Figure 7: Missing.\n\n"
            "Figure: No label.\n"
        )
        want = (
            "![Figure 6](https://arxiv.org/html/x/x6.png)\n\nFigure 6: Empty.\n\n"
            "Figure 7: Missing.\n\n"
            "No label.\n"
        )
        got = cleanup.clean(text, page())
        self.assertEqual(got, want)
        self.assertEqual(cleanup.clean(got, page()), got)

    def test_left_alone(self):
        for text in (
            "Figure: # 2 Heading.\n",
            "Figure: Figure 2: A.\nRefer to caption: https://e.com/a.png\nRefer to caption: https://e.com/b.png\n",
            "![Figure 3](https://e.com/a.png)\n\nFigure 2: Other label.\n",
            "![Figure 3](https://e.com/a.png)\nFigure 3: No blank line.\n",
            "```\nFigure: Figure 3: Fenced.\n```\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(cleanup.clean(text, page()), text)

    def test_without_page(self):
        text = "Figure: Figure 3: Drawn.\n"
        self.assertEqual(cleanup.clean(text), text)
        self.assertEqual(cleanup.clean(text, {}), "Figure 3: Drawn.\n")


class Fences(unittest.TestCase):
    def test_fenced_code_untouched(self):
        text = "```\n- \u2022\nFirst.\n$$ $a$ (1) $$\n```\n"
        self.assertEqual(cleanup.clean(text), text)

    def test_fence_length(self):
        text = "````\n```\n- \u2022 First.\n````\n- \u2022 Second.\n"
        self.assertEqual(cleanup.clean(text), "````\n```\n- \u2022 First.\n````\n- Second.\n")

    def test_fence_character(self):
        text = "~~~\n```\n- \u2022 First.\n~~~\n"
        self.assertEqual(cleanup.clean(text), text)


class Command(unittest.TestCase):
    def test_stdin_to_stdout(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "cleanup.py")],
            input="- \u2022 First.\n".encode("utf-8"),
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.decode("utf-8")
        self.assertEqual(out, "- First.\n")

    def test_page_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = os.path.join(tmp, "page.html")
            source = os.path.join(tmp, "source.md")
            with open(html, "w", encoding="utf-8") as f:
                f.write(PAGE)
            with open(source, "w", encoding="utf-8") as f:
                f.write("Figure: Figure 3: Drawn.\n")

            script = [sys.executable, os.path.join(HERE, "cleanup.py")]
            subprocess.run(script + ["--html", html, "--page-url", PAGE_URL, source, source], check=True)
            with open(source, encoding="utf-8") as f:
                self.assertEqual(f.read(), "Figure 3: Drawn.\n\n[Figure 3 on arXiv](%s#S3.F3)\n" % PAGE_URL)

            for bad in (
                ["--html", html],
                ["--page-url", PAGE_URL],
                ["--html", html, "--page-url", "http://arxiv.org/html/x"],
                ["--html", html, "--page-url", PAGE_URL + "/"],
                ["--html", html, "--page-url", PAGE_URL + "?v=1"],
            ):
                with self.subTest(bad=bad):
                    done = subprocess.run(script + bad + [source], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.assertEqual(done.returncode, 2)
                    self.assertEqual(done.stdout, b"")
                    self.assertIn(b"--page-url" if "--html" in bad and "--page-url" in bad else b"go together", done.stderr)

            with open(source, "w", encoding="utf-8") as f:
                f.write("Figure: Figure 3: Drawn.\n")
            other = "https://arxiv.org/html/9999.99999v1"
            done = subprocess.run(
                script + ["--html", html, "--page-url", other, source, source],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(done.returncode, 1)
            self.assertIn(b"not that paper's page", done.stderr)
            with open(source, encoding="utf-8") as f:
                self.assertEqual(f.read(), "Figure: Figure 3: Drawn.\n")


def headings(text):
    lines = text.split("\n")
    skip = cleanup.fenced(lines)
    return [line for line, fence in zip(lines, skip) if not fence and re.match(r"^#{1,6}\s", line)]


def references(text):
    m = re.search(r"^## References\n.*?(?=^## |\Z)", text, re.M | re.S)
    return None if m is None else m.group(0).rstrip("\n")


class Samples(unittest.TestCase):
    def samples(self):
        root = os.environ.get("CLEANUP_SAMPLES", "")
        if root == "":
            self.skipTest("CLEANUP_SAMPLES is not set")

        found = []
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name, "source.md")
            if os.path.isfile(path):
                found.append(path)
        if not found:
            self.skipTest("no */source.md under %s" % root)

        return found

    def test_samples(self):
        for path in self.samples():
            with self.subTest(path=path):
                with open(path, encoding="utf-8") as f:
                    before = f.read()
                after = cleanup.clean(before)

                self.assertEqual(headings(after), headings(before))
                self.assertIsNotNone(references(before))
                self.assertEqual(references(after), references(before))
                self.assertEqual(cleanup.clean(after), after)
                self.assertNotIn("- \u2022", after)
                self.assertNotRegex(after, r"(?m)^Figure: .*\nRefer to caption: https://")
                self.assertNotRegex(after, r"(?m)^\$\$ \$")
                self.assertNotRegex(after, r"\(\^(\d+)\^\1 ")


class PageSamples(unittest.TestCase):
    """CLEANUP_PAGES names a directory of <name>.md, arxiv2md's output, beside
    <name>.html, arXiv's page, and <name>.url, the URL it is served at."""

    def test_page_samples(self):
        root = os.environ.get("CLEANUP_PAGES", "")
        if root == "":
            self.skipTest("CLEANUP_PAGES is not set")

        names = sorted(n[:-3] for n in os.listdir(root) if n.endswith(".md"))
        names = [n for n in names if os.path.isfile(os.path.join(root, n + ".html"))]
        if not names:
            self.skipTest("no <name>.md beside <name>.html under %s" % root)

        for name in names:
            with self.subTest(name=name):
                base = os.path.join(root, name)
                with open(base + ".md", encoding="utf-8") as f:
                    before = f.read()
                with open(base + ".html", encoding="utf-8") as f:
                    html = f.read()
                with open(base + ".url", encoding="utf-8") as f:
                    url = f.read().strip()

                found = cleanup.page_figures(html, url)
                after = cleanup.clean(before, found)

                self.assertEqual(headings(after), headings(cleanup.clean(before)))
                self.assertEqual(references(after), references(before))
                self.assertEqual(cleanup.clean(after, found), after)
                self.assertNotRegex(after, r"(?m)^Figure: ")
                for number, (kind, urls, link) in found.items():
                    if kind == cleanup.HOSTED:
                        for u in urls:
                            self.assertIn("![Figure %s](%s)" % (number, u), after)
                    else:
                        self.assertIn("[Figure %s on arXiv](%s)" % (number, link), after)
                        self.assertNotRegex(after, r"(?m)^!\[Figure %s\]" % number)


if __name__ == "__main__":
    unittest.main()
