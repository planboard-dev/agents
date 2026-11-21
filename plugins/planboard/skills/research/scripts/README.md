`cleanup.py [--html <page> --page-url <url>] [<in> [<out>]]` undoes the markup arxiv2md adds when it
converts arXiv's HTML to markdown. It reads `<in>`, or stdin when `<in>` is missing or `-`, and
writes `<out>`, or stdout when `<out>` is missing or `-`. `<in>` and `<out>` may be the same file.
`--html` is arXiv's own HTML page for the paper and `--page-url` the URL it is served at,
`https://arxiv.org/html/<id>v<N>`. The two go together. The URL must be `https` with a lowercase
host, a path, and no user, port, query, fragment or trailing slash, and hold only letters, digits and
`` ._~%/+- `` after the host; any other exits `2`. It needs Python 3.9 or later and nothing outside
the standard library.

Each change matches one exact shape; a line that does not match is left as it is, and nothing inside
a fenced code block is touched. The text itself is never reworded.

- The abstract's first paragraph loses the doubled word: `Abstract The dominant...` becomes
  `The dominant...`. Only an uppercase letter after `Abstract ` marks it as doubled, so
  `Abstract interpretation is...` stays.
- `- •` followed by the item's text on the same line becomes one `- ` item. A `- •` alone on its
  line joins the next line only when that line is plain paragraph text; before a blank line, a
  heading, a list item, a fence, `$$` math, a table row, a quote or another `- •` it stays as it is.
- A footnote inlined as `(^N^N N text)` becomes `[^N]` in place, and `[^N]: text` is appended at the
  end of the document, after the References and any appendix. Parentheses inside `$...$` or
  `$$...$$` math do not count toward the closing one. A footnote whose closing parenthesis is not on
  the same line, whose math has no closing `$`, which holds an escaped parenthesis, or whose number
  is already used, is left alone.
- A display equation written `$$ $X$ (N) $$` becomes a `$$` block holding `X \tag{N}`, each line
  keeping the original line's indentation. A run of
  `$\displaystyle ...$` fragments becomes one `\begin{aligned}` block: a fragment that starts with a
  relation such as `=` joins the fragment before it as its right-hand side after `&`, and every
  other fragment starts a row.
- In the abstract, a plain-text copy directly followed by its LaTeX copy, such as `59 % 59\%`, keeps
  only the LaTeX, as inline math: `$59\%$`. This only happens when the abstract holds no `$` of its
  own and the LaTeX renders to exactly the plain text before it; an unknown command leaves the pair
  alone.
- `Figure: <caption>` directly followed by `Refer to caption: <https url>` becomes
  `![Figure N](<url>)`, with `Figure N` taken from the start of the caption or `Figure` when it has
  none, followed by the caption as its own paragraph, exactly as written. A `Figure:` line with no
  url after it, or whose caption would start a block of its own such as a heading, stays as it is
  unless the page below is given.

With `--html`, each figure the markdown holds, as a `Figure: <caption>` line with no url after it or
as `![Figure N](<url>)` lines one blank line apart followed by a blank line and a caption starting
`Figure N:`, is matched by `N` to the `<figure class="ltx_figure">` on the page whose own tag reads
`Figure N:`. Tables and subfigure tags such as `(a)` are not matched, and a number two figures on
the page share matches neither.

- A figure holding files arXiv hosts, as `<object type="image/svg+xml">` or plain `<img>`, and no
  inline `<svg>`, becomes one `![Figure N](<url>)` per `<object>` or `<img>` in it, in page order
  and one blank line apart, then the caption paragraph. This replaces any image arxiv2md wrote,
  whose `https://arxiv.org/html/<id>/<id>v<N>/...` URLs do not resolve, and adds the panels it
  left out. Each `data` or `src` is resolved against `--page-url`, and the figure is treated as
  unmatched when any result is not a URL `--page-url` itself would pass, or not below
  `<page-url>/`, such as another host, another paper, another version or a `..` segment.
- A figure holding an inline `<svg>`, a drawing LaTeXML wrote into the page, becomes the caption
  paragraph, a blank line and `[Figure N on arXiv](<page-url>#<figure id>)`. Any image arxiv2md
  took from inside the drawing, such as a logo, is dropped. A figure id other than letters, digits,
  `.`, `_` and `-` leaves the figure unmatched.
- A figure with no match keeps what arxiv2md wrote, except that a `Figure: <caption>` line becomes
  the caption paragraph without the prefix.

The caption is never changed, and a blank line follows the figure when the next line is not blank.
Without `--html` none of this happens. When the page's figures and tables hold images and none of
them is below `<page-url>/`, the page is another paper's or another version's: the script exits
`1`, saying so, and writes nothing. A page with no images cannot be checked this way.

A fence closes only with the same character it opened with, repeated at least as many times.

`cleanup_test.py` runs the tests: `python3 cleanup_test.py`. Setting `CLEANUP_SAMPLES` to a
directory of entries, such as a library's `Research/`, also runs the script over every
`*/source.md` below it and checks that the headings and the References section are unchanged and
that a second run changes nothing. Setting `CLEANUP_PAGES` to a directory holding `<name>.md`, what
arxiv2md or an earlier cleanup wrote, beside `<name>.html`, the saved page, and `<name>.url`, its
`--page-url`, runs the figure pass over each and checks the same, and that every matched figure
shows its panels or its link and no `Figure:` line is left.

`transcript.py [--auto] [--info-out <path>] <info.json> <captions> [<out>]` turns a YouTube caption
track into a markdown transcript. `<info.json>` is what `yt-dlp -j` printed for the video, or the
trimmed copy `--info-out` wrote on an earlier run. `<captions>` is the track yt-dlp wrote, json3 or
vtt, told apart by its `.json3` or `.vtt` extension. `--auto` says the track is YouTube's automatic
captions. It writes `<out>`, or stdout when `<out>` is missing or `-`. It needs Python 3.9 or later
and nothing outside the standard library, and its output depends only on its inputs.

- The document opens with `# <title>` and a list of the channel, the publish date from
  `upload_date`, the length from `duration` and the `https://www.youtube.com/watch?v=<id>` link. A
  fact the JSON lacks is left out.
- Each chapter in `chapters` is a `##` heading with the chapter's title, followed by a link to that
  second of the video, then the words that start at or after the chapter's start and before the
  next one's. A chapter titled with yt-dlp's placeholder `<Untitled Chapter N>`, or with nothing,
  is headed by its start time instead, such as `## 0:00`. A video without chapters has one
  `## Transcript` heading.
- The words are the caption text with non-breaking spaces and line breaks made single spaces. vtt
  tags such as `<c>` and `<i>` are removed and entities such as `&amp;` decoded. No word is changed,
  added or dropped, except the carried-over lines below.
- With `--auto`, a vtt track is de-duplicated. Automatic captions in vtt roll: a cue holds the line
  before it carried over above the new line, and a short cue between them holds the carried line
  above a blank one. A cue's first line is dropped when the cue has another line after it and the
  first line equals the line kept last. A cue holding only a line that repeats the last one is new
  speech and kept. Without `--auto` every line is kept, so a line said twice in a row stays twice.
  json3 carries each word once and is never de-duplicated.
- Paragraphs: a new one starts before a word when the paragraph holds 40 words and the speaker paused
  a second or more, when it holds 80 words and the previous word ends in `.`, `?` or `!`, or when it
  holds 200 words. The pause is the time from the previous word, or from the end of its cue when the
  track times whole cues rather than words. A chapter always starts a paragraph.
- The text is escaped so markdown renders it as written: a backslash goes before every
  `` \ ` * _ < > [ ] # & | ~ ``, before a leading `-`, `+` or `=`, and before the `.` or `)` of a
  leading number such as `1.`, so no paragraph opens a list, heading, quote or thematic break and
  nothing in it becomes emphasis, code, a link or raw HTML. CommonMark reads each of these escapes
  as the character alone. The title, the channel and the chapter titles are escaped the same way.
- `--info-out` writes the info JSON with only `id`, `title`, `description`, `channel`, `channel_id`,
  `upload_date`, `duration`, `language`, `chapters`, `tags`, `categories` and `webpage_url`.

It exits non-zero, writing nothing, when the info has no `id`, the captions are neither json3 nor
vtt, or the track holds no words, which it reports as `no caption text`.

`transcript_test.py` runs the tests: `python3 transcript_test.py`. Setting `TRANSCRIPT_SAMPLES` to a
directory holding `<name>.info.json` beside `<name>.json3` or `<name>.vtt`, as yt-dlp wrote them,
also converts each pair and checks that there is a heading per chapter, that no paragraph repeats
the one before or exceeds 200 words, and that every caption word appears once and unescapes to
itself. A pair whose info lists no uploaded track is converted as `--auto`.

`article.py` holds the steps of the article handler that are not trafilatura's own. It needs Python
3.9 or later and nothing outside the standard library. Values that come from the page, such as the
final URL, the base and the title, pass between its commands in files under a work directory
`<dir>`, never on a command line, since a site can put shell syntax in any of them.

`article.py fetch <url> <dir>` creates `<dir>` if needed, removes the files an earlier run left
there (`page.html`, `final.txt`, `base.txt`, `canonical.txt`, `article.json`, `article.md`,
`tavily.md`), downloads the page to `<dir>/page.html`, and writes one URL each to `final.txt`, the
URL after redirects, `base.txt`, what relative references resolve against, and `canonical.txt`, the
canonical form of the final URL. It prints `canonical: <url>`.

- A URL is refused, before any request, when it is not `http` or `https`, carries a user name or
  password, names `localhost` or a `*.localhost` host, or names or resolves to any address that is
  not global: loopback, private, link-local, shared, reserved and the like. An IPv6 address must be
  global and so must every IPv4 address it carries: IPv4-mapped (`::ffff:0:0/96`), IPv4-compatible
  (`::/96`), IPv4-translated (`::ffff:0:0:0/96`), NAT64 (`64:ff9b::/96`), 6to4 (`2002::/16`) and
  Teredo. NAT64 local-use, `64:ff9b:1::/48`, is refused outright. Every redirect is checked the
  same way before it is followed.
- The response must be `text/html` or `application/xhtml+xml` and at most 20 MB. The body is written
  as received.
- `base` is the page's first `<base href>` resolved against the final URL when that is `http` or
  `https`, otherwise the final URL.
- On a `403` or `429`, `base.txt` and `canonical.txt` are written from the canonical form of `<url>`
  as given, and there is no `page.html` or `final.txt`.
- It exits `2` with a `refused:` line for a refused URL or a response that is not a web page, `3`
  with `http <code>` for an error status, and `1` for anything else, such as a timeout.

The canonical form lowercases the scheme and host, drops a trailing dot on the host, a default port,
the fragment and the tracking parameters (every name starting `utm_`, and `fbclid`, `gclid`,
`dclid`, `gbraid`, `wbraid`, `msclkid`, `yclid`, `twclid`, `igshid`, `mc_cid`, `mc_eid`, `_hsenc`,
`_hsmi`, `mkt_tok`, `ref_src`, compared without case), and writes an empty path as `/`. `ref` is
kept, since GitHub and GitLab name a branch with it. The path and the remaining parameters, in their
order, are kept as written, except that any character other than letters, digits and
`` /%:@!$&()*+,;=-._~ `` is percent-encoded, so the URL holds no space, quote or backtick. Running
it over its own output changes nothing.

`article.py clean <dir> [<in> [<out>]]` makes converter markdown safe to render on the board,
resolving against the URL in `<dir>/base.txt`, which must be `http` or `https`. It reads `<in>`, or
stdin when `<in>` is missing or `-`, and writes `<out>`, or stdout when `<out>` is missing or `-`. Nothing inside a fenced code block or a code span is touched, and the text is never
reworded.

- An inline link or image destination with no scheme, such as `/x`, `../y`, `img/a.png`, `#sec` or
  `//cdn.example.org/z`, is resolved against the base. A destination with a scheme is left for the
  board, which passes only `http` and `https`.
- A `<` that CommonMark would read as the start of raw HTML (a tag, a closing tag, `<!` or `<?`) gets
  a backslash, so it shows as written rather than being dropped. Autolinks such as
  `<https://example.com>` and a `<` followed by anything else are left as they are.
- A line indented four columns or more that follows a blank line, which would open an indented code
  block, loses its indentation, unless it follows a list item, where it is the item's content.
  trafilatura carries the page's own HTML indentation into its markdown and writes code as fenced
  blocks, so an indented code block from it is never meant. Later lines of the same paragraph keep
  their indentation, which CommonMark reads as continuation.
- A line holding only spaces becomes empty.

A second run over its own output changes nothing.

`article.py meta <dir>` reads `<dir>/article.json`, what `trafilatura --json --with-metadata` wrote,
which is empty when it extracted nothing, and `<dir>/page.html`, treating a missing file as empty.
It prints `title:` and `published:` as `YYYY-MM-DD` when there is one to write, then `words:` and
`verdict:`. The title is trafilatura's, else the page's first `og:title`, else its first `<title>`,
whitespace collapsed. The date is left out when it is on or after
today or on January 1. `article.py words [<in>]` prints `words:` and `verdict:` for markdown.

Words are whitespace-separated tokens holding a letter or digit, not counting link destinations,
autolinks and bare `http` or `https` URLs. The verdict is `empty` for no words, `thin` for fewer
than 150, or fewer than 400 with a phrase saying the page needs JavaScript, and `ok` otherwise.

`article_test.py` runs the tests: `python3 article_test.py`. They use no network and look up no
names.

`local.py` holds the steps of the local handler that are not pdftotext's or pandoc's own. It needs
Python 3.9 or later and nothing outside the standard library, and imports `article.py` from its own
directory.

`local.py copy <path> <dir>` takes `<path>` when it starts with `/`, `~/`, `./` or `../`, or is a
`file:` URL with no host other than `localhost` and no query or fragment, whose percent escapes are
decoded. It resolves symlinks and refuses a path that does not exist, is not a regular file, has an
extension other than `.pdf`, `.md`, `.markdown`, `.html` or `.htm` in any case, or is named `.pdf`
with no `%PDF-` in its first 1024 bytes. Otherwise it removes `raw/`, `converted.md` and
`pdfinfo.txt` from `<dir>`, copies the file to `<dir>/raw/<name>`, hashing the bytes it copies, and
prints `type:` (`pdf`, `markdown` or `html`), `name:` and `canonical: local:sha256:<hex>`. `<name>`
is the file's name with each run of characters other than letters, digits, `.`, `_` and `-` made one
`-`, leading and trailing `.`, `_` and `-` dropped from the part before the extension, that part cut
to 100 characters and written `original` when nothing is left, and the extension lowercased. It
exits `2` with a `refused:` line for a refused path and `1` for anything else.

`local.py meta <dir>` reads the one file in `<dir>/raw/`, `<dir>/converted.md` and
`<dir>/pdfinfo.txt`, what `pdfinfo -enc UTF-8 -isodates` printed, treating a missing file as empty,
and prints `title:`, and `published:` when there is one. The title is, for a PDF, pdfinfo's `Title`;
for markdown, the `title:` in a YAML front matter block opening the file, quotes removed; for HTML,
the page's first `og:title`, else its first `<title>`. For markdown and HTML without one, it is the
first level-one ATX heading of `converted.md` outside a fence. Otherwise it is the copy's name
without its extension, `-` and `_` made spaces. Whitespace is collapsed. `published` is the date
part of pdfinfo's `CreationDate` when that is a real `YYYY-MM-DD` date, and only for a PDF.

`local.py clean [<in> [<out>]]` is `article.py clean` with no base. It reads `<in>`, or stdin when
`<in>` is missing or `-`, and writes `<out>`, or stdout when `<out>` is missing or `-`. Everything
`clean` does is done, except that an inline link or image whose destination has no scheme and does
not start with `#`, such as `other.md`, `/x`, `img/a.png` or `//cdn.example.org/z`, is replaced by
its text or alt text, since with no base it would resolve against the board. Spaces and tabs may
come between the `(` and the destination, and a line ending in `](` is first joined to the next line
when both are outside a fence and the next is not blank. The link's opening `[` is found by matching
brackets back from its `]`, skipping escaped ones, and a `!` before it marks an image. When the `[`
is not in the same run of text, because the link text holds a code span or starts on an earlier
line, or the link's `)` cannot be found after its destination, the destination becomes `<>`
instead. A destination with a scheme, a `#section` and an empty one are left as written.

A line outside a fence that could be a link reference definition, `[label]:` at its start or after
any run of `>` and list markers, with a label not starting `^`, has its `[` escaped unless its
destination, the first word after the colon or, when there is none, the first word of the next
line, with any `<...>` removed, starts `http://` or `https://` in any case. The definition then does
not form, so references to it render as text. A second run over its own output changes nothing.

`local_test.py` runs the tests: `python3 local_test.py`.
