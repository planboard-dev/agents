#!/usr/bin/env python3
#
# transcript.py [--auto] [--info-out <path>] <info.json> <captions> [<out>]
#
# Turns a YouTube caption track into a markdown transcript for source.md.
# <info.json> is what `yt-dlp -j` printed for the video, or the trimmed copy
# --info-out writes. <captions> is the track yt-dlp wrote, json3 or vtt, told
# apart by its extension. --auto says the track is YouTube's automatic
# captions. The markdown goes to <out>, or stdout when <out> is missing or
# "-". README.md in this directory describes the output.
#
# The output depends only on the inputs. Standard library only, Python 3.9.

import argparse
import html
import json
import re
import sys

# A paragraph ends at the first of these, checked before each word:
#   - it holds MIN_WORDS or more and the speaker paused PAUSE_MS or longer,
#   - it holds TARGET_WORDS or more and the previous word ends a sentence,
#   - it holds MAX_WORDS.
MIN_WORDS = 40
TARGET_WORDS = 80
MAX_WORDS = 200
PAUSE_MS = 1000

SENTENCE_END = re.compile(r"[.?!][\"')\]]*$")
UNTITLED = re.compile(r"^<Untitled Chapter \d+>$")

# Characters that are markdown syntax anywhere in a line, escaped with a
# backslash, which CommonMark reads as the character itself.
SYNTAX = re.compile(r"([\\`*_<>\[\]#&|~])")
# Characters that open a block (list, thematic break, setext underline) at
# the start of a line, and an ordered-list number.
LEADING = re.compile(r"^([-+=])")
NUMBERED = re.compile(r"^(\d+)([.)])")

VTT_TIMING = re.compile(r"^(\S+) --> (\S+)")
VTT_STAMP = re.compile(r"<(\d+:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})>")
VTT_TAG = re.compile(r"</?[^>]*>")

# The fields --info-out keeps. The rest of the yt-dlp output is stream
# formats, signed URLs and counters, which say nothing about the content.
INFO_FIELDS = (
    "id",
    "title",
    "description",
    "channel",
    "channel_id",
    "upload_date",
    "duration",
    "language",
    "chapters",
    "tags",
    "categories",
    "webpage_url",
)


class Word:
    __slots__ = ("start", "end", "text")

    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


def split_words(text):
    return text.replace(" ", " ").split()


def json3_words(data):
    """Words from a json3 track. An event with several segments is timed
    word by word, as auto-captions are; one with a single segment is a cue
    whose words all span the event."""
    words = []
    for event in data.get("events") or []:
        segs = event.get("segs") or []
        start = int(event.get("tStartMs", 0))
        if len(segs) > 1:
            for seg in segs:
                at = start + int(seg.get("tOffsetMs", 0))
                for w in split_words(seg.get("utf8", "")):
                    words.append(Word(at, at, w))
            continue

        end = start + int(event.get("dDurationMs", 0))
        for seg in segs:
            for w in split_words(seg.get("utf8", "")):
                words.append(Word(start, end, w))

    return words


def vtt_ms(stamp):
    parts = stamp.split(":")
    secs = float(parts[-1])
    mins = int(parts[-2])
    hours = int(parts[-3]) if len(parts) > 2 else 0
    return int(round(((hours * 60 + mins) * 60 + secs) * 1000))


def vtt_cues(text):
    """(start, end, lines) for each cue, lines as written."""
    cues = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        m = VTT_TIMING.match(lines[i].strip())
        if m is None:
            i += 1
            continue

        start = vtt_ms(m.group(1))
        end = vtt_ms(m.group(2))
        body = []
        i += 1
        # A cue ends at an empty line. Auto-caption cues hold lines of a
        # single space, which belong to the cue and are dropped as blank
        # by the caller.
        while i < len(lines) and lines[i] != "":
            body.append(lines[i])
            i += 1
        cues.append((start, end, body))

    return cues


def vtt_line_words(line, start, end):
    """Words of one cue line. Inline <hh:mm:ss.mmm> stamps time the words
    after them; a line without stamps is timed as the whole cue."""
    pieces = VTT_STAMP.split(line)
    words = []
    if len(pieces) == 1:
        for w in split_words(html.unescape(VTT_TAG.sub("", line))):
            words.append(Word(start, end, w))
        return words

    at = start
    for n, piece in enumerate(pieces):
        if n % 2 == 1:
            at = vtt_ms(piece)
            continue
        for w in split_words(html.unescape(VTT_TAG.sub("", piece))):
            words.append(Word(at, at, w))

    return words


def plain(line):
    return " ".join(split_words(html.unescape(VTT_TAG.sub("", line))))


def vtt_words(text, auto=False):
    """Words from a vtt track. Automatic captions in vtt roll: a cue holds
    two lines, the line before carried over above the new one, and a short
    cue between them holds the carried line above a blank one. With auto,
    a cue's first line is dropped as carried over when the cue has a line
    after it and the first line equals the line kept last. A cue whose only
    line repeats the last one is new speech and kept, as is every line of a
    track that is not auto."""
    words = []
    last = None
    for start, end, body in vtt_cues(text):
        for n, line in enumerate(body):
            flat = plain(line)
            if flat == "":
                continue
            if auto and n == 0 and len(body) > 1 and flat == last:
                continue
            words.extend(vtt_line_words(line, start, end))
            last = flat

    return words


def paragraphs(words):
    out = []
    current = []
    prev = None
    for w in words:
        if prev is not None and current:
            n = len(current)
            if (
                (n >= MIN_WORDS and w.start - prev.end >= PAUSE_MS)
                or (n >= TARGET_WORDS and SENTENCE_END.search(prev.text))
                or n >= MAX_WORDS
            ):
                out.append(inline(" ".join(current)))
                current = []
        current.append(w.text)
        prev = w

    if current:
        out.append(inline(" ".join(current)))

    return out


def inline(text):
    """Escapes text so markdown renders it as written: syntax characters
    anywhere, and a start that would open a list, heading, quote or
    thematic break rather than a paragraph."""
    text = SYNTAX.sub(r"\\\1", text)
    text = LEADING.sub(r"\\\1", text, count=1)
    return NUMBERED.sub(r"\1\\\2", text, count=1)


def clock(seconds):
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)


def one_line(text):
    return " ".join(str(text).split())


def chapter_title(chapter):
    """The chapter's title, escaped, or its start time when it has none or
    only yt-dlp's <Untitled Chapter N> placeholder."""
    title = one_line(chapter.get("title") or "")
    if title == "" or UNTITLED.match(title):
        return clock(float(chapter["start_time"]))
    return inline(title)


def watch_url(info):
    return "https://www.youtube.com/watch?v=%s" % info["id"]


def published(info):
    date = str(info.get("upload_date") or "")
    if re.match(r"^\d{8}$", date):
        return "%s-%s-%s" % (date[:4], date[4:6], date[6:])
    return ""


def render(info, words):
    lines = ["# %s" % inline(one_line(info.get("title") or info["id"])), ""]

    facts = []
    if info.get("channel"):
        facts.append("- Channel: %s" % inline(one_line(info["channel"])))
    if published(info):
        facts.append("- Published: %s" % published(info))
    if info.get("duration"):
        facts.append("- Length: %s" % clock(info["duration"]))
    facts.append("- Video: %s" % watch_url(info))
    lines.extend(facts)

    chapters = [c for c in info.get("chapters") or [] if "start_time" in c]
    if not chapters:
        lines.extend(["", "## Transcript"])
        for p in paragraphs(words):
            lines.extend(["", p])
        return "\n".join(lines) + "\n"

    starts = [int(float(c["start_time"]) * 1000) for c in chapters]
    groups = [[] for _ in chapters]
    for w in words:
        at = 0
        for n, s in enumerate(starts):
            if w.start >= s:
                at = n
        groups[at].append(w)

    for n, chapter in enumerate(chapters):
        secs = int(float(chapter["start_time"]))
        lines.extend(["", "## %s" % chapter_title(chapter), ""])
        lines.append("[%s](%s&t=%ds)" % (clock(secs), watch_url(info), secs))
        for p in paragraphs(groups[n]):
            lines.extend(["", p])

    return "\n".join(lines) + "\n"


def read_words(path, auto=False):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith(".json3"):
        return json3_words(json.loads(text))
    if path.endswith(".vtt"):
        return vtt_words(text, auto)
    raise ValueError("%s: captions must be .json3 or .vtt" % path)


def trimmed(info):
    return {k: info[k] for k in INFO_FIELDS if k in info}


def main(argv):
    parser = argparse.ArgumentParser(description="Markdown transcript from a YouTube caption track.")
    parser.add_argument("--auto", action="store_true", help="the track is YouTube's automatic captions")
    parser.add_argument("--info-out", help="also write the info JSON, trimmed, to this path")
    parser.add_argument("info")
    parser.add_argument("captions")
    parser.add_argument("out", nargs="?", default="-")
    args = parser.parse_args(argv)

    with open(args.info, encoding="utf-8") as f:
        info = json.load(f)
    if not info.get("id"):
        print("%s: no video id" % args.info, file=sys.stderr)
        return 1

    try:
        words = read_words(args.captions, args.auto)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    if not words:
        print("%s: no caption text" % args.captions, file=sys.stderr)
        return 1

    text = render(info, words)

    if args.info_out:
        with open(args.info_out, "w", encoding="utf-8") as f:
            json.dump(trimmed(info), f, ensure_ascii=False, indent=1)
            f.write("\n")

    if args.out == "-":
        sys.stdout.write(text)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
