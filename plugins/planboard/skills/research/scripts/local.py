#!/usr/bin/env python3
#
# local.py copy <path> <dir>
# local.py meta <dir>
# local.py clean [<in> [<out>]]
#
# The steps of the local handler that are not pdftotext's or pandoc's own.
# copy checks that <path> names a regular file of a handled type and copies it
# into <dir>/raw/ under a plain name, printing the type, that name and the
# canonical form, a hash of the content. meta reads the copy, the converted
# markdown and, for a PDF, what pdfinfo printed, for the title and the publish
# date. clean is article.py's cleanup with no base, so a relative link or
# image, which would resolve against the board, becomes its text. README.md in
# this directory lists what each does.
#
# Standard library only, Python 3.9.

import datetime
import hashlib
import os
import re
import shutil
import stat
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import article

# The file types the handler converts, by lowercase extension.
TYPES = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
}
HANDLED = ".pdf, .md, .markdown, .html and .htm"

# A copy's name keeps letters, digits, dots, underscores and hyphens, and a
# run of anything else becomes one hyphen.
UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
MAX_STEM = 100
# A PDF's header may follow a little junk, but not much.
PDF_HEAD = 1024

# What an earlier run left in the work directory.
STALE = ("raw", "converted.md", "pdfinfo.txt")

FRONT_TITLE = re.compile(r"^title:[ \t]*(.*?)[ \t]*$")
ATX = re.compile(r"^ {0,3}#[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
PDFINFO = re.compile(r"^([A-Za-z]+):[ \t]*(.*?)[ \t]*$")


class Refused(Exception):
    """An argument the handler does not take."""


def resolve(argument):
    """Returns the absolute path an argument names: an absolute path, one
    starting ~/, ./ or ../, or a file: URL with no host."""
    if argument.lower().startswith("file:"):
        parts = urllib.parse.urlsplit(argument)
        if parts.netloc not in ("", "localhost") or parts.query or parts.fragment:
            raise Refused("%s: a file: URL must name a file on this machine, with no host, query or fragment" % argument)
        path = urllib.parse.unquote(parts.path)
        if not path.startswith("/"):
            raise Refused("%s: a file: URL must hold an absolute path" % argument)
        return path
    if argument == "~" or argument.startswith("~/"):
        return os.path.expanduser(argument)
    if argument.startswith(("/", "./", "../")):
        return os.path.abspath(argument)
    raise Refused("%s is not a path: give one starting /, ~/, ./ or ../, or a file: URL" % argument)


def plain_name(path):
    """Returns the name the copy is kept under: the file's name with every run
    of characters other than letters, digits, dots, underscores and hyphens
    made one hyphen, starting with a letter or digit, and the extension in
    lowercase."""
    stem, extension = os.path.splitext(os.path.basename(path))
    stem = UNSAFE.sub("-", stem).strip("._-")
    stem = stem[:MAX_STEM].rstrip("._-") or "original"
    return stem + extension.lower()


def check(argument):
    """Returns the real path of the file an argument names and its type, or
    raises Refused for one that is missing, is not a regular file, or is not
    a type the handler converts."""
    path = os.path.realpath(resolve(argument))
    try:
        info = os.stat(path)
    except FileNotFoundError:
        raise Refused("%s: no such file" % argument)
    if not stat.S_ISREG(info.st_mode):
        raise Refused("%s is not a regular file" % argument)
    kind = TYPES.get(os.path.splitext(path)[1].lower())
    if kind is None:
        raise Refused("%s is not a type this handler converts: it takes %s" % (argument, HANDLED))
    return path, kind


def copy_into(argument, directory):
    """Copies the file an argument names into <directory>/raw/ and returns its
    type, the name of the copy and the canonical form of its content."""
    path, kind = check(argument)

    os.makedirs(directory, exist_ok=True)
    for name in STALE:
        stale = os.path.join(directory, name)
        if os.path.isdir(stale):
            shutil.rmtree(stale)
        elif os.path.exists(stale):
            os.remove(stale)

    name = plain_name(path)
    raw = os.path.join(directory, "raw")
    os.makedirs(raw)
    digest = hashlib.sha256()

    with open(path, "rb") as src:
        if not stat.S_ISREG(os.fstat(src.fileno()).st_mode):
            raise Refused("%s is not a regular file" % argument)
        head = src.read(PDF_HEAD)
        if kind == "pdf" and b"%PDF-" not in head:
            shutil.rmtree(raw)
            raise Refused("%s is named .pdf but is not a PDF" % argument)
        with open(os.path.join(raw, name), "xb") as dst:
            chunk = head
            while chunk:
                digest.update(chunk)
                dst.write(chunk)
                chunk = src.read(1 << 20)

    return kind, name, "local:sha256:" + digest.hexdigest()


def collapse(text):
    return " ".join((text or "").split())


def unquote(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def front_title(text):
    """Returns the title a YAML front matter block at the head of markdown
    names, or an empty string."""
    lines = text.lstrip(chr(0xFEFF)).split("\n")
    if not lines or lines[0].rstrip() != "---":
        return ""
    for line in lines[1:]:
        if line.rstrip() in ("---", "..."):
            break
        m = FRONT_TITLE.match(line)
        if m:
            return collapse(unquote(m.group(1)))
    return ""


def first_heading(text):
    """Returns the text of the first level-one ATX heading outside a fence, or
    an empty string."""
    lines = text.split("\n")
    for line, inside in zip(lines, article.fenced(lines)):
        if inside:
            continue
        m = ATX.match(line)
        if m:
            return collapse(m.group(1))
    return ""


def pdf_info(text):
    """Returns the title and the publish date pdfinfo printed, each empty when
    it has none."""
    fields = {}
    for line in text.split("\n"):
        m = PDFINFO.match(line)
        if m and m.group(1) not in fields:
            fields[m.group(1)] = m.group(2)
    date = fields.get("CreationDate", "")[:10]
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        date = ""
    return collapse(fields.get("Title")), date


def fallback_title(name):
    """Returns a title made from the copy's name: its stem with hyphens and
    underscores as spaces."""
    stem = os.path.splitext(name)[0]
    return collapse(stem.replace("-", " ").replace("_", " "))


def meta(directory):
    """Returns the title: and published: lines for the copy in
    <directory>/raw/."""
    raw = os.path.join(directory, "raw")
    names = sorted(os.listdir(raw))
    if len(names) != 1:
        raise ValueError("%s holds %d files, want the one copy" % (raw, len(names)))
    name = names[0]
    kind = TYPES[os.path.splitext(name)[1].lower()]
    converted = article.read_optional(os.path.join(directory, "converted.md"))

    title = ""
    published = ""
    if kind == "pdf":
        title, published = pdf_info(article.read_optional(os.path.join(directory, "pdfinfo.txt")))
    elif kind == "markdown":
        title = front_title(article.read_optional(os.path.join(raw, name)))
    else:
        title = article.page_title(article.read_optional(os.path.join(raw, name), "rb"))

    if not title and kind != "pdf":
        title = first_heading(converted)
    if not title:
        title = fallback_title(name)

    lines = ["title: %s" % title]
    if published:
        lines.append("published: %s" % published)
    return lines


def usage():
    print("usage: local.py copy <path> <dir> | meta <dir> | clean [<in> [<out>]]", file=sys.stderr)
    return 64


def main(argv):
    if not argv:
        return usage()
    command, args = argv[0], argv[1:]
    try:
        if command == "copy" and len(args) == 2:
            kind, name, canonical = copy_into(args[0], args[1])
            print("type: %s" % kind)
            print("name: %s" % name)
            print("canonical: %s" % canonical)
            return 0
        if command == "meta" and len(args) == 1:
            print("\n".join(meta(args[0])))
            return 0
        if command == "clean" and len(args) <= 2:
            text = article.read(args[0] if args else None)
            article.write(args[1] if len(args) > 1 else None, article.clean(text, None))
            return 0
    except Refused as e:
        print("refused: %s" % e, file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return usage()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
