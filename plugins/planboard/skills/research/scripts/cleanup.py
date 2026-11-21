#!/usr/bin/env python3
#
# cleanup.py [--html <page> --page-url <url>] [<in> [<out>]]
#
# Undoes markup that arxiv2md introduces when it converts arXiv's HTML to
# markdown, so that source.md reads as the paper does. It reads <in>, or stdin
# when <in> is missing or "-", and writes <out>, or stdout when <out> is
# missing or "-". With --html, arXiv's own HTML page for the paper, served at
# --page-url, is used to give figures arxiv2md could not show their panels or
# a link to the figure on arXiv's page. README.md in this directory lists the
# transformations.
#
# Every transformation matches one exact shape and leaves anything else as it
# is. The source text is never reworded. Standard library only, Python 3.9.

import argparse
import html.parser
import re
import sys
import urllib.parse

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^#{1,6}\s")
ABSTRACT_HEADING = re.compile(r"^#{1,6} Abstract\s*$")

FOOTNOTE_START = re.compile(r"\s*\(\^(\d+)\^\1 \1 ")
FOOTNOTE_USED = re.compile(r"\[\^([^\]]+)\]")

BULLET_ALONE = re.compile(r"^(\s*)- \u2022\s*$")
BULLET_INLINE = re.compile(r"^(\s*)- \u2022 +(\S.*)$")
# A line that starts a block of its own rather than continuing a paragraph.
BLOCK_START = re.compile(r"^\s*([#>|]|[-*+](\s|$)|\d+[.)](\s|$)|`{3,}|~{3,}|\$\$|={3,}\s*$|-{3,}\s*$)")

DISPLAY = re.compile(r"^(\s*)\$\$ (.+) \$\$\s*$")
DISPLAY_INNER = re.compile(r"((?:\$[^$]+\$\s*)+)(?:\((\d+)\))?")
FRAGMENT = re.compile(r"\$([^$]+)\$")
DISPLAYSTYLE = re.compile(r"^\\displaystyle(?![A-Za-z])\s*")
RELATION = re.compile(r"^(=|<|>|\\(leq|geq|le|ge|neq|approx|equiv|sim|coloneqq)(?![A-Za-z]))")

FIGURE = re.compile(r"^Figure: (\S.*)$")
FIGURE_LABEL = re.compile(r"^(Figure \d+)[:.]")
FIGURE_URL = re.compile(r"^Refer to caption: (https://[^\s()<>]+)\s*$")
FIGURE_IMAGE = re.compile(r"^!\[(Figure \d+)\]\((https://[^\s()<>]+)\)\s*$")
FIGURE_NUMBER = re.compile(r"^Figure (\d+)[:.]")

# What a figure on arXiv's page is made of.
HOSTED = "hosted"  # files arXiv hosts, one <object> or <img> per panel
DRAWING = "drawing"  # an <svg> LaTeXML wrote inline
PAGE_TAG = re.compile(r"^Figure (\d+):?$")
PAGE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
# An https URL with a lowercase host and a path of these characters only: no
# user, port, query, fragment, quote, bracket, backslash or space.
SAFE_URL = re.compile(r"^https://[a-z0-9.-]+(/[A-Za-z0-9._~%/+-]*)?$")


class PageError(Exception):
    """The page given with --html is not the one --page-url names."""

# What a LaTeX command in the abstract's doubled inline math renders as. A
# command missing from here makes the copy unrecognized, so it is left alone.
SYMBOLS = {
    "%": "%",
    "&": "&",
    "#": "#",
    "_": "_",
    "{": "{",
    "}": "}",
    ",": "",
    "!": "",
    ";": "",
    ":": "",
    " ": "",
    "times": "\u00d7",
    "to": "\u2192",
    "rightarrow": "\u2192",
    "approx": "\u2248",
    "sim": "\u223c",
    "leq": "\u2264",
    "le": "\u2264",
    "geq": "\u2265",
    "ge": "\u2265",
    "pm": "\u00b1",
    "infty": "\u221e",
}


def fenced(lines):
    """Returns one flag per line, true for a line inside or opening a fence."""
    flags = []
    opener = None
    for line in lines:
        m = FENCE.match(line)
        if opener is None:
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                opener = m.group(1)
                flags.append(True)
                continue
            flags.append(False)
            continue

        flags.append(True)
        # A fence closes only with the same character, at least as many of
        # them, and nothing else on the line.
        if m and m.group(1)[0] == opener[0] and len(m.group(1)) >= len(opener) and m.group(2).strip() == "":
            opener = None

    return flags


def closing_paren(text, start):
    """Returns the index of the ) that closes an ( already open at start.

    Parentheses inside $...$ math do not count. Returns -1 when there is no
    closing parenthesis or the balance is uncertain: an unclosed $ or an
    escaped parenthesis outside math.
    """
    depth = 1
    i = start
    while i < len(text):
        c = text[i]
        if c == "$":
            mark = "$$" if text.startswith("$$", i) else "$"
            end = text.find(mark, i + len(mark))
            if end < 0:
                return -1
            i = end + len(mark)
            continue
        if c == "\\" and i + 1 < len(text) and text[i + 1] in "()":
            return -1
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1

    return -1


def footnotes(lines, skip):
    """Turns (^N^N N text) into [^N] and returns the definitions to append."""
    used = set()
    for line in lines:
        used.update(FOOTNOTE_USED.findall(line))

    notes = []
    out = []
    for line, fence in zip(lines, skip):
        if fence:
            out.append(line)
            continue

        pos = 0
        result = ""
        while True:
            m = FOOTNOTE_START.search(line, pos)
            if m is None:
                break

            number = m.group(1)
            end = closing_paren(line, m.end())
            text = line[m.end():end].strip() if end >= 0 else ""
            if end < 0 or text == "" or number in used:
                result += line[pos:m.end()]
                pos = m.end()
                continue

            used.add(number)
            notes.append("[^%s]: %s" % (number, text))
            result += line[pos:m.start()] + "[^%s]" % number
            pos = end + 1

        out.append(result + line[pos:])

    return out, notes


def render(tex):
    """Returns what a LaTeX copy shows as plain text, or None if unsure."""
    out = ""
    i = 0
    while i < len(tex):
        c = tex[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+|.)", tex[i:])
            if m is None or m.group(1) not in SYMBOLS:
                return None
            out += SYMBOLS[m.group(1)]
            i += len(m.group(0))
            continue
        if c in "{}":
            i += 1
            continue
        if c in "^_~$":
            return None
        out += c
        i += 1

    return out


def plain(text):
    return text.replace("\u2212", "-")


def undouble(line):
    """Drops the plain copy in front of a LaTeX copy and marks the LaTeX as math."""
    tokens = re.split(r"(\s+)", line)
    words = [i for i, t in enumerate(tokens) if t != "" and not t.isspace()]
    drop = set()
    wrap = set()
    floor = 0

    for n, i in enumerate(words):
        token = tokens[i]
        if "\\" not in token and "{" not in token:
            continue

        shown = render(token)
        if not shown:
            continue

        acc = ""
        start = None
        for k in range(n - 1, floor - 1, -1):
            prev = tokens[words[k]]
            if re.search(r"[\\{}$]", prev):
                break
            acc = plain(prev) + acc
            if len(acc) >= len(shown):
                start = k
                break

        if start is None or acc != shown:
            continue

        for j in range(words[start], i):
            drop.add(j)
        wrap.add(i)
        floor = n + 1

    if not wrap:
        return line

    out = []
    for i, token in enumerate(tokens):
        if i in drop:
            continue
        if i in wrap:
            token = "$" + token + "$"
        out.append(token)

    return "".join(out)


def abstract(lines, skip):
    """Drops the doubled word and the doubled inline math in the abstract."""
    out = list(lines)
    for i, line in enumerate(lines):
        if skip[i] or not ABSTRACT_HEADING.match(line):
            continue

        end = i + 1
        while end < len(lines) and not HEADING.match(lines[end]) and not skip[end]:
            end += 1

        first = i + 1
        while first < end and lines[first].strip() == "":
            first += 1
        # The doubled word is followed by the abstract's first sentence, so an
        # uppercase letter. "Abstract interpretation is" is the paper's own.
        rest = lines[first][len("Abstract "):] if first < end else ""
        if first < end and lines[first].startswith("Abstract ") and rest[:1].isupper():
            out[first] = rest

        if any("$" in lines[k] for k in range(i + 1, end)):
            break

        for k in range(i + 1, end):
            out[k] = undouble(out[k])

        break

    return out


def paragraph_text(line, fence):
    """Reports whether line is plain paragraph text rather than a block of its own."""
    if fence or line.strip() == "":
        return False

    return BLOCK_START.match(line) is None


def bullets(lines, skip):
    """Collapses - followed by a bullet character into one list marker."""
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if skip[i]:
            out.append(line)
            i += 1
            continue

        m = BULLET_INLINE.match(line)
        if m:
            out.append("%s- %s" % (m.group(1), m.group(2)))
            i += 1
            continue

        m = BULLET_ALONE.match(line)
        if m and i + 1 < len(lines) and paragraph_text(lines[i + 1], skip[i + 1]):
            out.append("%s- %s" % (m.group(1), lines[i + 1].strip()))
            i += 2
            continue

        out.append(line)
        i += 1

    return out


def display_body(inner):
    """Returns the $$ block for the inside of a double-wrapped equation, or None."""
    m = DISPLAY_INNER.fullmatch(inner.strip())
    if m is None:
        return None

    frags = FRAGMENT.findall(m.group(1))
    number = m.group(2)
    styled = [DISPLAYSTYLE.match(f) is not None for f in frags]

    if len(frags) == 1:
        body = DISPLAYSTYLE.sub("", frags[0]).strip()
    elif all(styled):
        rows = []
        aligned = False
        for f in frags:
            f = DISPLAYSTYLE.sub("", f).strip()
            if RELATION.match(f) and rows and "&" not in rows[-1]:
                rows[-1] += " &" + f
                aligned = True
                continue
            rows.append(f)

        if any("&" in f or "\\\\" in f for f in frags):
            return None

        if aligned or len(rows) > 1:
            body = "\\begin{aligned}\n" + " \\\\\n".join(rows) + "\n\\end{aligned}"
        else:
            body = rows[0]
    else:
        return None

    if body == "":
        return None
    if number is not None:
        body += " \\tag{%s}" % number

    return "$$\n" + body + "\n$$"


def display(lines, skip):
    """Unwraps $$ $...$ (N) $$ into one $$ block with the number as a tag."""
    out = []
    for line, fence in zip(lines, skip):
        m = None if fence else DISPLAY.match(line)
        body = display_body(m.group(2)) if m else None
        if body is None:
            out.append(line)
            continue

        # The indentation is kept so a block inside a list item stays there.
        out.append("\n".join(m.group(1) + row for row in body.split("\n")))

    return out


def figures(lines, skip):
    """Turns a Figure: caption and its Refer to caption: url into an image and the caption."""
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        fig = None if skip[i] else FIGURE.match(line)
        url = FIGURE_URL.match(lines[i + 1]) if fig and i + 1 < len(lines) and not skip[i + 1] else None
        again = i + 2 < len(lines) and FIGURE_URL.match(lines[i + 2])

        # The caption becomes a paragraph of its own, so one that would start
        # a different block is left alone.
        if fig and url and not again and paragraph_text(fig.group(1), False):
            caption = fig.group(1)
            label = FIGURE_LABEL.match(caption)
            out.append("![%s](%s)" % (label.group(1) if label else "Figure", url.group(1)))
            out.append("")
            out.append(caption)
            # A blank line ends the caption's paragraph, so a trailing
            # backslash cannot join it to the next line as a hard break.
            if i + 2 < len(lines) and lines[i + 2].strip() != "":
                out.append("")
            i += 2
            continue

        out.append(line)
        i += 1

    return out


class PageParser(html.parser.HTMLParser):
    """Collects each <figure class="ltx_figure"> on arXiv's page.

    A figure records its id, the text of its own "Figure N:" tag, its
    panels, the SVG files it holds as <object> and the images it holds as
    <img>, in page order, and whether it holds an inline <svg>. Everything
    inside a figure counts toward every figure it sits in. panels holds the
    panels of every figure and table on the page.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.figures = []
        self.panels = []
        self.open = []
        self.tag = None
        self.tag_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.tag is not None and tag == "span":
            self.tag_depth += 1

        if tag == "figure":
            classes = (a.get("class") or "").split()
            fig = {
                "keep": "ltx_figure" in classes,
                "id": a.get("id") or "",
                "tag": None,
                "panels": [],
                "svg": False,
            }
            self.open.append(fig)
            if fig["keep"]:
                self.figures.append(fig)
            return

        if not self.open:
            return

        if tag == "svg":
            for fig in self.open:
                fig["svg"] = True
        elif tag == "object" and (a.get("type") or "") == "image/svg+xml" and a.get("data"):
            self.panels.append(a["data"])
            for fig in self.open:
                fig["panels"].append(a["data"])
        elif tag == "img" and a.get("src"):
            self.panels.append(a["src"])
            for fig in self.open:
                fig["panels"].append(a["src"])
        elif tag == "span" and self.tag is None:
            classes = (a.get("class") or "").split()
            inner = self.open[-1]
            if "ltx_tag_figure" in classes and inner["tag"] is None:
                self.tag = inner
                self.tag_depth = 1
                inner["tag"] = ""

    def handle_startendtag(self, tag, attrs):
        # <img/> and <svg/> have no end tag to wait for.
        self.handle_starttag(tag, attrs)
        if tag == "figure":
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "span" and self.tag is not None:
            self.tag_depth -= 1
            if self.tag_depth == 0:
                self.tag = None
        elif tag == "figure" and self.open:
            if self.tag is self.open[-1]:
                self.tag = None
            self.open.pop()

    def handle_data(self, data):
        if self.tag is not None:
            self.tag["tag"] += data


def page_url_error(page_url):
    """Returns why page_url cannot name arXiv's page for a paper, or None."""
    if not SAFE_URL.match(page_url):
        return "--page-url must be an https URL with a lowercase host and no user, port, query or fragment"

    path = urllib.parse.urlsplit(page_url).path
    if path.strip("/") == "":
        return "--page-url must name the paper's page, https://arxiv.org/html/<id>v<N>"
    if path.endswith("/"):
        return "--page-url must not end in /, since the page's image paths resolve against it"

    return None


def panel_url(page_url, panel):
    """Resolves a panel's data or src against page_url.

    Returns None unless the result is a safe URL below the page's own
    directory, https://arxiv.org/html/<id>v<N>/, on the page's host.
    """
    url = urllib.parse.urljoin(page_url, panel.strip())
    if not SAFE_URL.match(url):
        return None

    base = urllib.parse.urlsplit(page_url)
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(parts.path)
    if parts.netloc != base.netloc or not path.startswith(base.path + "/"):
        return None
    if "/../" in path + "/" or "/./" in path + "/":
        return None

    return url


def page_figures(page, page_url):
    """Returns {N: (kind, panel urls, link)} for the figures on arXiv's page.

    Only a figure whose tag reads "Figure N:" is kept, and a number that two
    figures share is dropped. A hosted figure, one with <object> or <img>
    panels and no inline <svg>, keeps its panels, each resolved by
    panel_url. A drawing keeps a link to itself on the page. A figure that
    is neither, or whose panels or id are not safe to write into markdown,
    is dropped.

    Raises PageError when the page's figures and tables hold panels and
    none of them resolves below page_url: the page is another paper's, or
    another version's.
    """
    reason = page_url_error(page_url)
    if reason is not None:
        raise PageError(reason)

    parser = PageParser()
    parser.feed(page)
    parser.close()

    if parser.panels and all(panel_url(page_url, p) is None for p in parser.panels):
        raise PageError("no image on the page is below %s/, so it is not that paper's page" % page_url)

    found = {}
    seen = set()
    for fig in parser.figures:
        m = PAGE_TAG.match(" ".join((fig["tag"] or "").split()))
        if m is None:
            continue

        number = m.group(1)
        if number in seen:
            found.pop(number, None)
            continue
        seen.add(number)

        if fig["svg"]:
            if PAGE_ID.match(fig["id"]):
                found[number] = (DRAWING, [], "%s#%s" % (page_url, fig["id"]))
            continue

        urls = []
        for panel in fig["panels"]:
            url = panel_url(page_url, panel)
            if url is None:
                urls = []
                break
            urls.append(url)
        if urls:
            found[number] = (HOSTED, urls, None)

    return found


def figure_number(caption):
    m = FIGURE_NUMBER.match(caption)
    return None if m is None else m.group(1)


def ends_block(out, lines, after):
    """Adds a blank line when the line after the emitted block is not blank."""
    if after < len(lines) and lines[after].strip() != "":
        out.append("")


def emit_figure(out, kind, urls, link, caption):
    if kind == HOSTED:
        for url in urls:
            out.append("![Figure %s](%s)" % (figure_number(caption), url))
            out.append("")
        out.append(caption)
        return

    out.append(caption)
    out.append("")
    out.append("[Figure %s on arXiv](%s)" % (figure_number(caption), link))


def image_run(lines, skip, i):
    """Matches ![Figure N](url) lines, one blank line apart, then a blank and the caption.

    Returns (caption, index after the caption) or None.
    """
    m = FIGURE_IMAGE.match(lines[i])
    label = m.group(1)
    j = i + 1
    while True:
        if j + 1 >= len(lines) or lines[j].strip() != "" or skip[j + 1]:
            return None
        nxt = FIGURE_IMAGE.match(lines[j + 1])
        if nxt and nxt.group(1) == label:
            j += 2
            continue
        break

    caption = lines[j + 1]
    fig = FIGURE_LABEL.match(caption)
    if fig is None or fig.group(1) != label or not paragraph_text(caption, False):
        return None

    return caption, j + 2


def page_pass(lines, skip, page):
    """Rewrites each figure that arXiv's page shows as hosted SVG files or an inline drawing."""
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if skip[i]:
            out.append(line)
            i += 1
            continue

        bare = FIGURE.match(line)
        if bare and not (i + 1 < len(lines) and FIGURE_URL.match(lines[i + 1])) and paragraph_text(bare.group(1), False):
            caption = bare.group(1)
            number = figure_number(caption)
            if number in page:
                emit_figure(out, *page[number], caption)
            else:
                out.append(caption)
            ends_block(out, lines, i + 1)
            i += 1
            continue

        run = image_run(lines, skip, i) if FIGURE_IMAGE.match(line) else None
        if run and figure_number(run[0]) in page:
            caption, after = run
            emit_figure(out, *page[figure_number(caption)], caption)
            ends_block(out, lines, after)
            i = after
            continue

        out.append(line)
        i += 1

    return out


def clean(text, page=None):
    """Cleans arxiv2md markdown; page is what page_figures returned, or None."""
    trailing = text.endswith("\n")
    lines = text.split("\n")
    if trailing:
        lines = lines[:-1]

    lines, notes = footnotes(lines, fenced(lines))
    lines = abstract(lines, fenced(lines))
    lines = bullets(lines, fenced(lines))
    # display writes several lines into one element; split them before the
    # next pass looks for fences.
    lines = "\n".join(display(lines, fenced(lines))).split("\n")
    lines = figures(lines, fenced(lines))
    if page is not None:
        lines = page_pass(lines, fenced(lines), page)

    if notes:
        while lines and lines[-1].strip() == "":
            lines.pop()
        lines.append("")
        lines.extend(notes)

    out = "\n".join(lines)
    if trailing or notes:
        out += "\n"

    return out


def main(argv):
    parser = argparse.ArgumentParser(description="Undoes the markup arxiv2md adds to a paper.")
    parser.add_argument("--html", help="arXiv's HTML page for the paper")
    parser.add_argument("--page-url", help="the URL the page is served at, https://arxiv.org/html/<id>v<N>")
    parser.add_argument("source", nargs="?", default="-")
    parser.add_argument("target", nargs="?", default="-")
    args = parser.parse_args(argv)

    if (args.html is None) != (args.page_url is None):
        parser.error("--html and --page-url go together")
    if args.page_url is not None and page_url_error(args.page_url) is not None:
        parser.error(page_url_error(args.page_url))

    page = None
    if args.html is not None:
        with open(args.html, encoding="utf-8", errors="replace") as f:
            html_text = f.read()
        try:
            page = page_figures(html_text, args.page_url)
        except PageError as e:
            sys.stderr.write("%s: %s: %s\n" % (parser.prog, args.html, e))
            return 1

    if args.source == "-":
        text = sys.stdin.buffer.read().decode("utf-8")
    else:
        with open(args.source, encoding="utf-8") as f:
            text = f.read()

    result = clean(text, page)

    if args.target == "-":
        sys.stdout.buffer.write(result.encode("utf-8"))
    else:
        with open(args.target, "w", encoding="utf-8") as f:
            f.write(result)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
