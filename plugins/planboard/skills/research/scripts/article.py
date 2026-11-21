#!/usr/bin/env python3
#
# article.py fetch <url> <dir>
# article.py clean <dir> [<in> [<out>]]
# article.py meta <dir>
# article.py words [<in>]
#
# The steps of the article handler that are not trafilatura's own. fetch
# downloads a web page into <dir> after refusing addresses that are not on
# the public internet, and writes the final URL, the base for relative
# references and the canonical form to files beside it. clean makes converter
# markdown safe to render on the board, reading the base from <dir>. meta
# reads trafilatura's JSON and the page in <dir> for the title, the publish
# date and whether the extraction found the body. words does the last for
# any markdown. Values that come from the page travel between the commands
# in files, never on a command line. README.md in this directory lists what
# each does.
#
# Standard library only, Python 3.9.

import datetime
import html.parser
import ipaddress
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "Mozilla/5.0 (compatible; planboard-research)"
TIMEOUT = 30
MAX_BYTES = 20 * 1024 * 1024
HTML_TYPES = ("text/html", "application/xhtml+xml")

# Query parameters that say where a link was shared rather than what it names.
# Every parameter whose name starts with utm_ is one too.
TRACKING = {
    "fbclid",
    "gclid",
    "dclid",
    "gbraid",
    "wbraid",
    "msclkid",
    "yclid",
    "twclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "_hsenc",
    "_hsmi",
    "mkt_tok",
    "ref_src",
}
DEFAULT_PORTS = {"http": 80, "https": 443}

# IPv6 ranges whose low 32 bits are an IPv4 address: IPv4-compatible,
# IPv4-mapped, IPv4-translated (SIIT) and the NAT64 well-known prefix.
EMBEDS_IPV4 = [
    ipaddress.ip_network(n) for n in ("::/96", "::ffff:0:0/96", "::ffff:0:0:0/96", "64:ff9b::/96")
]
# NAT64 local-use, which places the IPv4 address by a local convention.
LOCAL_NAT64 = ipaddress.ip_network("64:ff9b:1::/48")

# Characters kept as they are in a canonical path or query; any other is
# percent-encoded, so the URL holds no space, quote or other character a
# shell or YAML would read.
URL_SAFE = "/%:@!$&()*+,;=-._~"

# The extraction missed the body when it holds fewer than THIN_WORDS words, or
# fewer than NOTICE_WORDS and says the page needs JavaScript.
THIN_WORDS = 150
NOTICE_WORDS = 400
JS_NOTICE = re.compile(
    r"\b(enable|enabled|requires?|required|turn on|needs?)\b[^.\n]{0,40}\bjavascript\b"
    r"|\bjavascript\b[^.\n]{0,40}\b(required|disabled|needed|is off)\b",
    re.IGNORECASE,
)
WORD = re.compile(r"\w", re.UNICODE)
DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])(\s|$)")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# The destination of an inline link or image, after its "](": either <...> or
# a run without spaces in which parentheses are balanced one deep.
DESTINATION = re.compile(r"(?<!\\)\]\((<[^<>\n]*>|[^\s()<>]*(?:\([^\s()<>]*\)[^\s()<>]*)*)")
# What follows an inline destination up to the link's closing parenthesis: an
# optional title in double quotes, single quotes or parentheses.
LINK_END = re.compile(r"""[ \t]*(?:"[^"\n]*"|'[^'\n]*'|\([^()\n]*\))?[ \t]*\)""")
# The same destination with the spaces and tabs CommonMark allows before it,
# for markdown with no base, where a relative one must not slip past.
LOOSE_DESTINATION = re.compile(r"(?<!\\)\]\([ \t]*(<[^<>\n]*>|[^\s()<>]*(?:\([^\s()<>]*\)[^\s()<>]*)*)")
# A line ending in an inline link's "](", whose destination CommonMark lets
# start on the next line.
OPEN_AT_END = re.compile(r"(?<!\\)\]\([ \t]*$")
# A line that could be a link reference definition, inside any number of
# block quotes and list items: the prefix, then the label and whatever follows
# the colon on the line. A label starting "^" is a footnote, not a link.
DEFINITION = re.compile(
    r"^((?:[ \t]*(?:>|[-*+][ \t]|\d{1,9}[.)][ \t]))*[ \t]*)\[(?!\^)((?:[^\[\]\\\n]|\\.)+)\]:[ \t]*(\S*)"
)
WEB = re.compile(r"^https?://", re.IGNORECASE)
# A "<" that CommonMark would read as the start of raw HTML: a tag, a closing
# tag, a comment or declaration, or a processing instruction.
RAW_HTML = re.compile(r"(?<!\\)<(?=[A-Za-z][A-Za-z0-9-]*(?:[\s/>]|$)|/[A-Za-z]|!|\?)")
URL_TEXT = re.compile(r"\]\([^)]*\)|<[A-Za-z][A-Za-z0-9+.-]*:[^>]*>|https?://\S+")


class Refused(Exception):
    """A URL the handler must not fetch."""


class HTTPStatus(Exception):
    """The server answered with an error status."""

    def __init__(self, code):
        super().__init__("http %d" % code)
        self.code = code


def split_url(url):
    """Returns the parts of an http or https URL, refusing any other."""
    try:
        parts = urllib.parse.urlsplit(url.strip())
        port = parts.port
    except ValueError as e:
        raise Refused("%s: %s" % (url, e))
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise Refused("%s: only http and https URLs are fetched" % url)
    if parts.username is not None or parts.password is not None:
        raise Refused("%s: a URL carrying credentials is not fetched" % url)
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise Refused("%s: no host" % url)
    return scheme, host, port, parts


def canonical(url):
    """Returns url with its scheme and host lowercased, the default port, the
    fragment and tracking parameters removed, and an empty path made "/". The
    path and the other parameters, in their order, are kept as written, except
    that characters outside URL_SAFE, such as a space or a quote, are
    percent-encoded."""
    scheme, host, port, parts = split_url(url)
    netloc = "[%s]" % host if ":" in host else host
    if port is not None and port != DEFAULT_PORTS[scheme]:
        netloc += ":%d" % port
    kept = []
    for piece in parts.query.split("&"):
        if not piece:
            continue
        name = urllib.parse.unquote_plus(piece.split("=", 1)[0]).lower()
        if name.startswith("utm_") or name in TRACKING:
            continue
        kept.append(urllib.parse.quote(piece, safe=URL_SAFE))
    path = urllib.parse.quote(parts.path or "/", safe=URL_SAFE)
    return urllib.parse.urlunsplit((scheme, netloc, path, "&".join(kept), ""))


def embedded_ipv4(ip):
    """Returns the IPv4 addresses an IPv6 address carries: mapped, 6to4,
    Teredo, or the low 32 bits of a range in EMBEDS_IPV4."""
    found = []
    if ip.ipv4_mapped is not None:
        found.append(ip.ipv4_mapped)
    if ip.sixtofour is not None:
        found.append(ip.sixtofour)
    if ip.teredo is not None:
        found.extend(ip.teredo)
    for network in EMBEDS_IPV4:
        if ip in network:
            found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return found


def public_address(address):
    """Reports whether an address is on the public internet. An IPv6 address
    must be global itself and so must every IPv4 address it carries."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if not ip.is_global:
        return False
    if ip.version == 4:
        return True
    if ip in LOCAL_NAT64:
        return False
    return all(v4.is_global for v4 in embedded_ipv4(ip))


def check(url):
    """Refuses a URL that is not http or https, or whose host is or resolves to
    an address that is not on the public internet, such as localhost or a
    private network."""
    scheme, host, port, _ = split_url(url)
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(".localhost"):
        raise Refused("%s: %s is this machine" % (url, host))
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not public_address(host):
            raise Refused("%s: %s is not a public address" % (url, host))
        return
    try:
        infos = socket.getaddrinfo(host, port or DEFAULT_PORTS[scheme], proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise Refused("%s: %s does not resolve: %s" % (url, host, e))
    for info in infos:
        address = info[4][0]
        if not public_address(address):
            raise Refused("%s: %s resolves to %s, which is not a public address" % (url, host, address))


class CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HeadFinder(html.parser.HTMLParser):
    """Collects the page's first <base href>, og:title and <title>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.href = None
        self.og_title = None
        self.title = None
        self.in_title = False
        self.title_parts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "base" and self.href is None and values.get("href"):
            self.href = values["href"].strip()
        if tag == "meta" and self.og_title is None and (values.get("property") or "").lower() == "og:title":
            self.og_title = values.get("content")
        if tag == "title" and self.title is None:
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title" and self.in_title:
            self.in_title = False
            self.title = "".join(self.title_parts)

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)


def read_head(body):
    finder = HeadFinder()
    try:
        finder.feed(body.decode("utf-8", errors="replace"))
        finder.close()
    except Exception:
        pass
    return finder


def page_base(final, body):
    """Returns the URL relative references resolve against: the page's first
    <base href> when it is http or https, otherwise the final URL."""
    href = read_head(body).href
    if href is None:
        return final
    joined = urllib.parse.urljoin(final, href)
    if urllib.parse.urlsplit(joined).scheme.lower() not in DEFAULT_PORTS:
        return final
    return joined


def page_title(body):
    """Returns the page's og:title, else its <title>, whitespace collapsed, or
    an empty string."""
    head = read_head(body)
    for title in (head.og_title, head.title):
        title = " ".join((title or "").split())
        if title:
            return title
    return ""


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


# The files the handler keeps in its work directory.
STALE = ("page.html", "final.txt", "base.txt", "canonical.txt", "article.json", "article.md", "tavily.md")


def fetch_into(url, directory):
    """Fetches url into directory: page.html, and final.txt, base.txt and
    canonical.txt holding one URL each. Every file in STALE is removed first,
    so nothing from an earlier run is read as this one's. When the server
    answers 403 or 429,
    base.txt and canonical.txt are written from url as given before the
    HTTPStatus is raised, for the fallback. Returns the canonical form."""
    os.makedirs(directory, exist_ok=True)
    for name in STALE:
        path = os.path.join(directory, name)
        if os.path.exists(path):
            os.remove(path)
    try:
        final, base, canon = fetch(url, os.path.join(directory, "page.html"))
    except HTTPStatus as e:
        if e.code in (403, 429):
            canon = canonical(url)
            write_text(os.path.join(directory, "base.txt"), canon)
            write_text(os.path.join(directory, "canonical.txt"), canon)
        raise
    write_text(os.path.join(directory, "final.txt"), final)
    write_text(os.path.join(directory, "base.txt"), base)
    write_text(os.path.join(directory, "canonical.txt"), canon)
    return canon


def fetch(url, out):
    """Downloads url to out, checking it and every redirect first. Returns the
    final URL, the base and the canonical form."""
    check(url)
    opener = urllib.request.build_opener(CheckedRedirects())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        response = opener.open(request, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        raise HTTPStatus(e.code)
    with response:
        final = response.geturl()
        kind = (response.headers.get_content_type() or "").lower()
        if kind not in HTML_TYPES:
            raise Refused("%s: %s is not a web page" % (final, kind))
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise Refused("%s: larger than %d bytes" % (final, MAX_BYTES))
    with open(out, "wb") as f:
        f.write(body)
    return final, page_base(final, body), canonical(final)


def fenced(lines):
    """Returns one flag per line, true for a line inside, opening or closing a
    fence."""
    flags = []
    opener = None
    for line in lines:
        m = FENCE.match(line)
        if opener is None:
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                opener = m.group(1)
            flags.append(opener is not None)
            continue
        flags.append(True)
        if m and m.group(1)[0] == opener[0] and len(m.group(1)) >= len(opener) and not m.group(2).strip():
            opener = None
    return flags


def code_spans(line):
    """Splits a line into (text, is_code) pieces at its code spans."""
    pieces = []
    start = i = 0
    while i < len(line):
        c = line[i]
        if c == "\\":
            i += 2
            continue
        if c != "`":
            i += 1
            continue
        j = i
        while j < len(line) and line[j] == "`":
            j += 1
        width = j - i
        k = j
        end = -1
        while k < len(line):
            if line[k] != "`":
                k += 1
                continue
            m = k
            while m < len(line) and line[m] == "`":
                m += 1
            if m - k == width:
                end = m
                break
            k = m
        if end < 0:
            i = j
            continue
        pieces.append((line[start:i], False))
        pieces.append((line[i:end], True))
        start = i = end
    pieces.append((line[start:], False))
    return pieces


def absolute(destination, base):
    """Resolves a destination with no scheme against base."""
    wrapped = destination.startswith("<")
    inner = destination[1:-1] if wrapped else destination
    if not inner or SCHEME.match(inner):
        return destination
    joined = urllib.parse.urljoin(base, inner)
    return "<%s>" % joined if wrapped else joined


def relative(destination):
    """Reports whether a destination is a reference with no scheme, other than
    one within the page, which is what a base would resolve."""
    inner = destination[1:-1] if destination.startswith("<") else destination
    return bool(inner) and not inner.startswith("#") and not SCHEME.match(inner)


def escaped(text, i):
    """Reports whether the character at i is escaped by an odd run of
    backslashes before it."""
    run = 0
    while i - run > 0 and text[i - run - 1] == "\\":
        run += 1
    return run % 2 == 1


def opener(text):
    """Returns the index of the "[" that a "]" placed after text would close,
    or -1 when text holds none."""
    depth = 0
    for i in range(len(text) - 1, -1, -1):
        if text[i] not in "[]" or escaped(text, i):
            continue
        if text[i] == "]":
            depth += 1
        elif depth == 0:
            return i
        else:
            depth -= 1
    return -1


def inert(out, text, m):
    """Replaces the link or image whose destination m matched by its text or
    alt text, for markdown with no base to resolve against. out is what was
    written before the "]". Returns the new out and where to go on reading
    text, or None when the link's opening "[" is not in out, such as when its
    text holds a code span, or its closing ")" does not follow."""
    end = LINK_END.match(text, m.end())
    start = opener(out)
    if end is None or start < 0:
        return None
    label = out[start + 1:]
    if start > 0 and out[start - 1] == "!" and not escaped(out, start - 1):
        start -= 1
    return out[:start] + label, end.end()


def inline(text, base):
    """Rewrites the text outside code spans: link and image destinations made
    absolute, and a "<" that would open raw HTML escaped. With no base, a
    link or image whose destination is relative becomes its text instead,
    since it would resolve against the board, and an empty destination when
    its text cannot be found."""
    out = ""
    at = 0
    pattern = DESTINATION if base is not None else LOOSE_DESTINATION
    for m in pattern.finditer(text):
        if m.start() < at:
            continue
        out += RAW_HTML.sub(r"\\<", text[at:m.start()])
        at = m.end()
        if base is not None:
            out += "](" + absolute(m.group(1), base)
            continue
        if not relative(m.group(1)):
            out += m.group(0)
            continue
        replaced = inert(out, text, m)
        if replaced is None:
            out += "](<>"
            continue
        out, at = replaced
    out += RAW_HTML.sub(r"\\<", text[at:])
    return out


def indent_width(line):
    width = 0
    for c in line:
        if c == " ":
            width += 1
        elif c == "\t":
            width += 4 - width % 4
        else:
            break
    return width


def join_destinations(lines):
    """Joins a line ending in an inline link's "](" to the line after it, when
    both are outside a fence and the next is not blank, so a destination
    CommonMark reads across the line ending is on the line with its link."""
    flags = fenced(lines)
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        while (
            not flags[i]
            and OPEN_AT_END.search(line)
            and i + 1 < len(lines)
            and not flags[i + 1]
            and lines[i + 1].strip()
        ):
            i += 1
            line = line.rstrip(" \t") + lines[i].lstrip(" \t")
        out.append(line)
        i += 1
    return out


def inert_definitions(lines):
    """Escapes the "[" of every line outside a fence that could be a link
    reference definition whose destination, on that line or else the next, is
    not an http or https URL. The line then shows as the text it is, and a
    reference to its label, full, collapsed or shortcut, finds no definition
    and shows as text too. A footnote, "[^label]:", is left alone."""
    flags = fenced(lines)
    out = list(lines)
    for i, line in enumerate(lines):
        if flags[i]:
            continue
        m = DEFINITION.match(line)
        if not m:
            continue
        destination = m.group(3)
        if not destination and i + 1 < len(lines) and not flags[i + 1]:
            following = lines[i + 1].split()
            destination = following[0] if following else ""
        if destination.startswith("<"):
            destination = destination[1:].split(">", 1)[0]
        if WEB.match(destination):
            continue
        out[i] = line[:m.end(1)] + "\\" + line[m.end(1):]
    return out


def clean(text, base):
    """Makes converter markdown safe to render on the board. base is the URL
    relative destinations resolve against, or None for a document with no
    origin, whose relative links and images become their text."""
    lines = text.split("\n")
    if base is None:
        lines = inert_definitions(join_destinations(lines))
    flags = fenced(lines)
    out = []
    blank_before = True
    in_list = False
    for line, inside in zip(lines, flags):
        if inside:
            out.append(line)
            blank_before = False
            in_list = False
            continue
        if not line.strip():
            out.append("")
            blank_before = True
            continue
        indent = indent_width(line)
        if blank_before and indent >= 4 and not in_list:
            line = line.lstrip(" \t")
            indent = 0
        if LIST_ITEM.match(line):
            in_list = True
        elif blank_before and indent == 0:
            in_list = False
        blank_before = False
        out.append("".join(p if code else inline(p, base) for p, code in code_spans(line)))
    return "\n".join(out)


def count_words(text):
    """Counts the words of prose: link destinations and URLs are not words, and
    neither is a token without a letter or digit, such as "-" or "|"."""
    text = URL_TEXT.sub(" ", text)
    return sum(1 for token in text.split() if WORD.search(token))


def verdict(text, words):
    if words == 0:
        return "empty"
    if words < THIN_WORDS:
        return "thin"
    if words < NOTICE_WORDS and JS_NOTICE.search(text):
        return "thin"
    return "ok"


def published(value, today):
    """Returns trafilatura's date as YYYY-MM-DD, or None when it is missing,
    today or later, which is the date of the fetch or an update rather than of
    publication, or January 1, which is how a bare year is written."""
    m = DATE.match(value or "")
    if not m:
        return None
    try:
        day = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    if day >= today or (day.month == 1 and day.day == 1):
        return None
    return day.isoformat()


def meta(data, today, fallback_title=""):
    """Returns the lines meta prints for trafilatura's JSON, which is empty
    when it extracted nothing or trafilatura did not run. The title is
    trafilatura's, else fallback_title, the one in the page's head."""
    doc = json.loads(data) if data.strip() else {}
    text = doc.get("text") or ""
    words = count_words(text)
    lines = []
    title = " ".join((doc.get("title") or "").split()) or fallback_title
    if title:
        lines.append("title: %s" % title)
    day = published(doc.get("date"), today)
    if day:
        lines.append("published: %s" % day)
    lines.append("words: %d" % words)
    lines.append("verdict: %s" % verdict(text, words))
    return lines


def read(path):
    if path in (None, "-"):
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    if path in (None, "-"):
        sys.stdout.write(text)
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def usage():
    print(
        "usage: article.py fetch <url> <dir> | clean <dir> [<in> [<out>]] | meta <dir> | words [<in>]",
        file=sys.stderr,
    )
    return 64


def read_optional(path, mode="r"):
    if not os.path.exists(path):
        return "" if mode == "r" else b""
    if mode == "r":
        return read(path)
    with open(path, "rb") as f:
        return f.read()


def main(argv):
    if not argv:
        return usage()
    command, args = argv[0], argv[1:]
    try:
        if command == "fetch" and len(args) == 2:
            print("canonical: %s" % fetch_into(args[0], args[1]))
            return 0
        if command == "clean" and 1 <= len(args) <= 3:
            base = read_text(os.path.join(args[0], "base.txt"))
            split_url(base)
            text = read(args[1] if len(args) > 1 else None)
            write(args[2] if len(args) > 2 else None, clean(text, base))
            return 0
        if command == "meta" and len(args) == 1:
            data = read_optional(os.path.join(args[0], "article.json"))
            title = page_title(read_optional(os.path.join(args[0], "page.html"), "rb"))
            print("\n".join(meta(data, datetime.date.today(), title)))
            return 0
        if command == "words" and len(args) <= 1:
            text = read(args[0] if args else None)
            words = count_words(text)
            print("words: %d" % words)
            print("verdict: %s" % verdict(text, words))
            return 0
    except Refused as e:
        print("refused: %s" % e, file=sys.stderr)
        return 2
    except HTTPStatus as e:
        print(str(e), file=sys.stderr)
        return 3
    except (OSError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return usage()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
