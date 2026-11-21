# The youtube handler

The body is the video's English caption track, turned into a transcript by the skill's
`transcript.py`. yt-dlp gives the metadata and the captions; the video itself is never downloaded.
An uploaded track is used when the video has one, and YouTube's automatic captions only when it does
not.

## Recognizing

A URL on `youtube.com`, `www.youtube.com`, `m.youtube.com`, `music.youtube.com`,
`www.youtube-nocookie.com` or `youtu.be`, `http` or `https`, naming one video:

- `/watch?v=<id>`, with `v` anywhere in the query.
- `youtu.be/<id>`.
- `/embed/<id>`, `/shorts/<id>`, `/live/<id>` and `/v/<id>`.

A video id is eleven characters from `A-Z`, `a-z`, `0-9`, `-` and `_`. Other query parameters, such
as `t`, `si`, `feature`, `list` and `index`, are ignored: a `watch` URL inside a playlist is the one
video, not the playlist. A playlist, channel or search URL names no single video and is not handled;
say so and stop. A bare id is not recognized, since nothing marks it as YouTube.

## Tools

| Tool         | Needed for                        | Check                                        | Install                                              |
|--------------|-----------------------------------|----------------------------------------------|------------------------------------------------------|
| `yt-dlp`     | the metadata and the captions     | `command -v yt-dlp`                          | `brew install yt-dlp`; `python3 -m pip install -U "yt-dlp[default]"` |
| `deno` or `node` | yt-dlp's YouTube extraction   | `command -v deno`, then `command -v node`    | `brew install deno`; `apt install nodejs`            |
| `python3`    | `transcript.py`                   | `command -v python3`                         | `xcode-select --install` on macOS; `apt install python3` |

yt-dlp runs a JavaScript runtime to extract YouTube pages. Without one it warns that extraction is
deprecated and may miss data, so the run needs one. It enables only `deno` by default. When `deno`
is missing and `node` is present, add `--js-runtimes node` to every `yt-dlp` call below instead of
installing `deno`. The runtime executes scripts from the `yt-dlp-ejs` package, which the Homebrew
and `yt-dlp[default]` installs include. `yt-dlp -v -j <url>` names the runtime it found in its
`[debug] JS runtimes:` line.

All three are needed, so a missing one that the user declines to install stops the run before any
fetch.

yt-dlp prints warnings about `ffmpeg` and impersonation on every call. Neither matters for captions;
ignore them.

## Identity

- `canonical` is `youtube:<id>`: `youtube:oV9rvDllKEg`. The short, long, embed, shorts and live
  forms of one video are one entry.
- `url` is `https://www.youtube.com/watch?v=<id>`, with no other parameters.

Every `yt-dlp` call below gets that `url`, not the argument as typed, so a `list` parameter never
turns a call into a playlist fetch.

## Metadata

```
yt-dlp -j "https://www.youtube.com/watch?v=<id>" > <scratchpad>/youtube-<id>.json
```

A non-zero exit is a failure: quote the last `ERROR:` line, which names a private, removed or
age-restricted video. Otherwise read the JSON:

| meta.yaml   | From the JSON                                                       |
|-------------|---------------------------------------------------------------------|
| `title`     | `title`, whitespace collapsed                                       |
| `published` | `upload_date`, `YYYYMMDD`, written `YYYY-MM-DD`                     |

A video has no `version`. `live_status` must be `not_live` or `was_live`; a stream that is live,
upcoming or still processing (`is_live`, `is_upcoming`, `post_live`) has no settled captions, so
say so and stop. `chapters`, `channel` and `duration` go into the transcript through
`transcript.py`, not into `meta.yaml`.

## Content

### Choosing the track

List the caption tracks the JSON offers:

```
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("uploaded:", *sorted(d.get("subtitles") or {})); print("auto:", *sorted(k for k in d.get("automatic_captions") or {} if k.startswith("en") or k.endswith("-orig")))' <scratchpad>/youtube-<id>.json
```

Take the first of these that exists:

1. An uploaded track `en`, then the first uploaded `en-*` in sorted order, such as `en-GB` or
   `en-US`.
2. The automatic track `en-orig`, which is YouTube's recognition of English speech.
3. The automatic track `en`, only when no automatic track ends in `-orig`. When another language's
   `<lang>-orig` is listed, `en` is a machine translation of that language, not a transcript.

If none exists, say the video has no English captions, uploaded or automatic, and stop. No entry is
written.

### Fetching it

```
mkdir -p <build>/raw
yt-dlp --load-info-json <scratchpad>/youtube-<id>.json --skip-download \
  --write-subs --sub-langs '<track>' --sub-format 'json3/vtt' \
  -o '<build>/raw/captions.%(ext)s'
```

For an automatic track, use `--write-auto-subs` in place of `--write-subs`. Pass exactly one of the
two: with both, yt-dlp writes one file per language code, the uploaded track winning where both
have that code, and the file name does not say which it was. `--sub-langs` matches the whole code,
so `en` does not also fetch `en-orig` or `en-US`. `--load-info-json` reuses the metadata call rather
than extracting the page again.

The file is `<build>/raw/captions.<track>.json3`, or `.vtt` when YouTube offers no json3. No file
after a zero exit is a failure.

### The transcript

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/research/scripts/transcript.py" \
  --info-out "<build>/raw/info.json" \
  <scratchpad>/youtube-<id>.json "<build>/raw/captions.<track>.<ext>" "<build>/source.md"
```

For an automatic track, add `--auto` before `--info-out`. It turns on the vtt de-duplication, which
an uploaded track must not get, since a line said twice in a row is two lines there.

`source.md` opens with the title and a list of the channel, the publish date, the length and the
link, then the transcript in paragraphs. A video with chapters has a `##` heading per chapter over
its stretch of the transcript, each starting with a link to that point in the video; one without
has a single `## Transcript`; a chapter with no title of its own is headed by its start time. The
vtt form of automatic captions carries each line over into the cue after it, and with `--auto` the
script keeps each line once. The text is backslash-escaped so markdown renders it as spoken.
`scripts/README.md` lists what it does.

"no caption text" on a non-zero exit means the track was empty: say the video has no English
captions and stop, as above. Any other non-zero exit is a failure. Do not edit `source.md` by hand.

`raw/` keeps the caption file and `info.json`, the yt-dlp JSON trimmed to the fields that describe
the video. The full JSON stays in the scratchpad: it is mostly stream URLs, which expire and carry
the fetching machine's address.

Set `converter: yt-dlp+transcript`. For an automatic track, also set `lossy: true`: it is speech
recognition, with no punctuation or capitalization, misheard names and terms, and no marks for a
change of speaker. An uploaded track is not marked lossy. Neither carries what is only on screen,
such as slides and code, which is true of every transcript and is what the kind is.
