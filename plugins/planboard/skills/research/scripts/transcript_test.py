#!/usr/bin/env python3
#
# Tests transcript.py with small made-up tracks in both formats, and, when
# TRANSCRIPT_SAMPLES names a directory holding pairs of real yt-dlp output
# (<name>.info.json beside <name>.json3 or <name>.vtt), a check that each
# converts to a transcript holding every chapter and no rolled-over lines.
# Run with: python3 transcript_test.py

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import transcript


def info(**extra):
    base = {"id": "abc123DEF_-", "title": "A  Talk:\n about things"}
    base.update(extra)
    return base


def auto_event(start, words, gap=300):
    segs = [{"utf8": words[0]}]
    for n, w in enumerate(words[1:], 1):
        segs.append({"utf8": " " + w, "tOffsetMs": n * gap})
    return {"tStartMs": start, "dDurationMs": 4000, "wWinId": 1, "segs": segs}


def cue_event(start, dur, text):
    return {"tStartMs": start, "dDurationMs": dur, "segs": [{"utf8": text}]}


def body(md):
    """The transcript's paragraphs, without the title and facts."""
    return md.split("\n## ", 1)[1].split("\n", 1)[1].strip("\n").split("\n\n")


class Json3(unittest.TestCase):
    def test_auto_words(self):
        data = {
            "events": [
                {"tStartMs": 0, "dDurationMs": 9000, "id": 1},
                auto_event(100, ["so", "what", "is"]),
                {"tStartMs": 1000, "dDurationMs": 10, "aAppend": 1, "segs": [{"utf8": "\n"}]},
                auto_event(1010, ["concurrency", "well"]),
            ]
        }
        words = transcript.json3_words(data)
        self.assertEqual([w.text for w in words], ["so", "what", "is", "concurrency", "well"])
        self.assertEqual([w.start for w in words], [100, 400, 700, 1010, 1310])
        self.assertEqual(words[0].start, words[0].end)

    def test_uploaded_cues(self):
        data = {"events": [cue_event(120, 2720, "Hi everyone.\nI gave this talk ")]}
        words = transcript.json3_words(data)
        self.assertEqual([w.text for w in words], ["Hi", "everyone.", "I", "gave", "this", "talk"])
        self.assertTrue(all(w.start == 120 and w.end == 2840 for w in words))


# "_" stands for the lines holding a single space that yt-dlp writes, which
# an editor trimming trailing whitespace would otherwise empty.
VTT_ROLLING = """WEBVTT
Kind: captions
Language: en

00:00:03.959 --> 00:00:05.550 align:start position:0%
_
you<00:00:04.160><c> if</c><00:00:04.279><c> you</c><00:00:04.560><c> looked</c>

00:00:05.550 --> 00:00:05.560 align:start position:0%
you if you looked
_

00:00:05.560 --> 00:00:07.869 align:start position:0%
you if you looked
at<00:00:06.240><c> the</c><00:00:06.399><c> languages</c>

00:00:07.869 --> 00:00:07.879 align:start position:0%
at the languages
_

00:00:07.879 --> 00:00:11.030 align:start position:0%
at the languages
of<00:00:08.360><c> today</c>
""".replace("\n_\n", "\n \n")

VTT_UPLOADED = """WEBVTT

1
00:00:00.120 --> 00:00:02.840
Hi everyone. Q&amp;A is
<i>at the end.</i>

2
00:00:02.840 --> 00:00:05.120
No.

3
00:00:05.120 --> 00:00:06.000
No.
Really.
"""

# A speaker saying "no" twice, as automatic captions roll it: the second
# "no" arrives as a new line under the carried first one.
VTT_ROLLING_REPEAT = """WEBVTT

00:00:01.000 --> 00:00:02.000
_
no

00:00:02.000 --> 00:00:02.010
no
_

00:00:02.010 --> 00:00:03.000
no
no

00:00:03.000 --> 00:00:03.010
no
_

00:00:05.000 --> 00:00:06.000
no
""".replace("\n_\n", "\n \n")


class Vtt(unittest.TestCase):
    def test_rolling_lines_once(self):
        words = transcript.vtt_words(VTT_ROLLING, auto=True)
        self.assertEqual(
            " ".join(w.text for w in words),
            "you if you looked at the languages of today",
        )
        self.assertEqual(words[0].start, 3959)
        self.assertEqual(words[1].start, 4160)
        self.assertEqual(words[-1].start, 8360)

    def test_rolling_repeat_kept(self):
        words = transcript.vtt_words(VTT_ROLLING_REPEAT, auto=True)
        self.assertEqual(" ".join(w.text for w in words), "no no no")

    def test_not_auto_keeps_every_line(self):
        words = transcript.vtt_words(VTT_ROLLING)
        self.assertEqual(
            " ".join(w.text for w in words),
            "you if you looked you if you looked you if you looked at the languages "
            "at the languages at the languages of today",
        )

    def test_uploaded(self):
        words = transcript.vtt_words(VTT_UPLOADED)
        self.assertEqual(" ".join(w.text for w in words), "Hi everyone. Q&A is at the end. No. No. Really.")
        self.assertEqual((words[0].start, words[0].end), (120, 2840))

    def test_hours(self):
        self.assertEqual(transcript.vtt_ms("01:02:03.456"), 3723456)
        self.assertEqual(transcript.vtt_ms("02:03.456"), 123456)


def words_of(texts, step=100, pauses=()):
    out = []
    at = 0
    for n, t in enumerate(texts):
        if n in pauses:
            at += 5000
        out.append(transcript.Word(at, at, t))
        at += step
    return out


class Paragraphs(unittest.TestCase):
    def test_pause_after_min(self):
        texts = ["w%d" % n for n in range(60)]
        got = transcript.paragraphs(words_of(texts, pauses=(10, 45)))
        self.assertEqual([len(p.split()) for p in got], [45, 15])

    def test_sentence_after_target(self):
        texts = ["w%d" % n for n in range(120)]
        texts[84] = "end."
        texts[90] = "again?"
        got = transcript.paragraphs(words_of(texts))
        self.assertEqual([len(p.split()) for p in got], [85, 35])
        self.assertTrue(got[0].endswith("end."))

    def test_max(self):
        got = transcript.paragraphs(words_of(["w"] * 450))
        self.assertEqual([len(p.split()) for p in got], [200, 200, 50])

    def test_block_starts_escaped(self):
        self.assertEqual(transcript.inline("# one"), "\\# one")
        self.assertEqual(transcript.inline("- two"), "\\- two")
        self.assertEqual(transcript.inline("--- three"), "\\--- three")
        self.assertEqual(transcript.inline("+ four"), "\\+ four")
        self.assertEqual(transcript.inline("= five"), "\\= five")
        self.assertEqual(transcript.inline("> six"), "\\> six")
        self.assertEqual(transcript.inline("3. seven"), "3\\. seven")
        self.assertEqual(transcript.inline("12) eight"), "12\\) eight")
        self.assertEqual(transcript.inline("3.5 nine"), "3\\.5 nine")

    def test_inline_syntax_escaped(self):
        self.assertEqual(
            transcript.inline("a slice of <T> and a*b*c or [x](y) #1 `go` \\n"),
            "a slice of \\<T\\> and a\\*b\\*c or \\[x\\](y) \\#1 \\`go\\` \\\\n",
        )

    def test_escapes_round_trip(self):
        # CommonMark turns a backslash before ASCII punctuation into the
        # punctuation alone, so removing those escapes gives what renders.
        cases = [
            "a slice of <T> is a*b*c",
            "__init__ and ~~gone~~ in a | b",
            "* star start",
            "***",
            "- - -",
            "1. first",
            "## heading",
            "back\\slash \\* and \\\\",
            "Q&A &amp; more",
            "=== setext",
        ]
        for text in cases:
            with self.subTest(text=text):
                got = transcript.inline(text)
                self.assertEqual(unescape(got), text)
                self.assertNotRegex(got, r"^([#>*+=|~`]|-\s|-{3}|\d+[.)])")


def unescape(text):
    return re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", text)


class Render(unittest.TestCase):
    def test_no_chapters(self):
        md = transcript.render(
            info(channel="Gophers", upload_date="20231205", duration=2324),
            words_of(["Hello", "there."]),
        )
        self.assertEqual(
            md,
            "# A Talk: about things\n\n"
            "- Channel: Gophers\n"
            "- Published: 2023-12-05\n"
            "- Length: 38:44\n"
            "- Video: https://www.youtube.com/watch?v=abc123DEF_-\n\n"
            "## Transcript\n\n"
            "Hello there.\n",
        )

    def test_missing_facts_left_out(self):
        md = transcript.render(info(upload_date="2023"), words_of(["Hi."]))
        self.assertNotIn("Channel", md)
        self.assertNotIn("Published", md)
        self.assertNotIn("Length", md)

    def test_chapters(self):
        chapters = [
            {"start_time": 0.0, "end_time": 2.0, "title": "<Untitled Chapter 1>"},
            {"start_time": 2.0, "end_time": 3725.0, "title": "What Is\nConcurrency <T>"},
            {"start_time": 3725.0, "end_time": 4000.0, "title": "<Untitled Chapter 3>"},
        ]
        words = [
            transcript.Word(100, 100, "intro"),
            transcript.Word(1999, 1999, "words."),
            transcript.Word(2000, 2000, "first"),
            transcript.Word(3725500, 3725500, "last"),
        ]
        md = transcript.render(info(chapters=chapters), words)
        self.assertIn(
            "## 0:00\n\n"
            "[0:00](https://www.youtube.com/watch?v=abc123DEF_-&t=0s)\n\n"
            "intro words.\n\n"
            "## What Is Concurrency \\<T\\>\n\n"
            "[0:02](https://www.youtube.com/watch?v=abc123DEF_-&t=2s)\n\n"
            "first\n\n"
            "## 1:02:05\n\n"
            "[1:02:05](https://www.youtube.com/watch?v=abc123DEF_-&t=3725s)\n\n"
            "last\n",
            md,
        )
        self.assertNotIn("## Transcript", md)

    def test_empty_chapter_keeps_heading(self):
        chapters = [{"start_time": 0, "title": "A"}, {"start_time": 10, "title": "B"}]
        md = transcript.render(info(chapters=chapters), [transcript.Word(20000, 20000, "x")])
        self.assertIn("## A\n\n[0:00](https://www.youtube.com/watch?v=abc123DEF_-&t=0s)\n\n## B\n", md)

    def test_chapter_title_by_time(self):
        self.assertEqual(transcript.chapter_title({"start_time": 75.4, "title": "  "}), "1:15")
        self.assertEqual(transcript.chapter_title({"start_time": 0, "title": "<Untitled Chapter 12>"}), "0:00")
        self.assertEqual(
            transcript.chapter_title({"start_time": 0, "title": "<Untitled Chapter> of mine"}),
            "\\<Untitled Chapter\\> of mine",
        )

    def test_title_and_channel_escaped(self):
        md = transcript.render(info(title="Generics: []T and *T", channel="a_b"), words_of(["x"]))
        self.assertTrue(md.startswith("# Generics: \\[\\]T and \\*T\n\n- Channel: a\\_b\n"))


class Command(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(HERE, "transcript.py")] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_files_and_trimmed_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            info_path = os.path.join(tmp, "video.info.json")
            caps = os.path.join(tmp, "captions.en.json3")
            out = os.path.join(tmp, "source.md")
            trimmed = os.path.join(tmp, "info.json")
            full = info(channel="Gophers", formats=[{"url": "https://x/?ip=1"}], view_count=7)
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(full, f)
            with open(caps, "w", encoding="utf-8") as f:
                json.dump({"events": [cue_event(0, 1000, "Hello.")]}, f)

            got = self.run_script("--info-out", trimmed, info_path, caps, out)
            self.assertEqual(got.returncode, 0, got.stderr)
            with open(out, encoding="utf-8") as f:
                first = f.read()
            with open(trimmed, encoding="utf-8") as f:
                kept = json.load(f)
            self.assertEqual(sorted(kept), ["channel", "id", "title"])

            again = self.run_script(trimmed, caps)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(again.stdout.decode("utf-8"), first)

    def test_auto_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            info_path = os.path.join(tmp, "info.json")
            caps = os.path.join(tmp, "captions.en-orig.vtt")
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(info(), f)
            with open(caps, "w", encoding="utf-8") as f:
                f.write(VTT_ROLLING)
            plain_run = self.run_script(info_path, caps)
            auto_run = self.run_script("--auto", info_path, caps)
            self.assertEqual(auto_run.returncode, 0, auto_run.stderr)
            self.assertIn(b"\nyou if you looked at the languages of today\n", auto_run.stdout)
            self.assertIn(b"you if you looked you if you looked", plain_run.stdout)

    def test_no_text_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            info_path = os.path.join(tmp, "info.json")
            caps = os.path.join(tmp, "captions.en.vtt")
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(info(), f)
            with open(caps, "w", encoding="utf-8") as f:
                f.write("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n \n")
            got = self.run_script(info_path, caps)
            self.assertNotEqual(got.returncode, 0)
            self.assertIn(b"no caption text", got.stderr)

    def test_unknown_format_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            info_path = os.path.join(tmp, "info.json")
            caps = os.path.join(tmp, "captions.en.srv3")
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(info(), f)
            with open(caps, "w", encoding="utf-8") as f:
                f.write("<timedtext/>")
            got = self.run_script(info_path, caps)
            self.assertNotEqual(got.returncode, 0)


class Samples(unittest.TestCase):
    def samples(self):
        root = os.environ.get("TRANSCRIPT_SAMPLES", "")
        if root == "":
            self.skipTest("TRANSCRIPT_SAMPLES is not set")

        found = []
        for name in sorted(os.listdir(root)):
            if not name.endswith(".info.json"):
                continue
            stem = os.path.join(root, name[: -len(".info.json")])
            for ext in (".json3", ".vtt"):
                if os.path.isfile(stem + ext):
                    found.append((stem + ".info.json", stem + ext))
        if not found:
            self.skipTest("no <name>.info.json with <name>.json3 or <name>.vtt under %s" % root)

        return found

    def test_samples(self):
        for info_path, caps in self.samples():
            with self.subTest(captions=caps):
                with open(info_path, encoding="utf-8") as f:
                    meta = json.load(f)
                # The handler takes an uploaded track when there is one.
                auto = not (meta.get("subtitles") or {})
                words = transcript.read_words(caps, auto)
                md = transcript.render(meta, words)

                self.assertGreater(len(words), 0)
                chapters = meta.get("chapters") or []
                self.assertEqual(len(re.findall(r"(?m)^## ", md)), max(1, len(chapters)))
                paras = [
                    p for p in md.strip("\n").split("\n\n")
                    if not p.startswith(("#", "- ")) and not re.match(r"^\[\d[\d:]*\]\(https://", p)
                ]
                for a, b in zip(paras, paras[1:]):
                    self.assertNotEqual(a, b)
                for p in paras:
                    self.assertLessEqual(len(p.split()), transcript.MAX_WORDS)
                self.assertEqual(sum(len(p.split()) for p in paras), len(words))
                self.assertEqual(unescape(" ".join(paras)).split(), [w.text for w in words])


if __name__ == "__main__":
    unittest.main()
