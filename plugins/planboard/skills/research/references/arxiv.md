# The arxiv handler

The body comes from arxiv2md, which converts arXiv's own HTML rendering of a paper to markdown. The
metadata comes from the arXiv API. A paper with no HTML rendering falls back to its PDF through
`pdftotext`.

## Recognizing

Any of these, with or without a version suffix such as `v7`:

- `https://arxiv.org/abs/<id>`, `/html/<id>` or `/pdf/<id>`, with or without `www.` or `export.`,
  and for `/pdf/` with or without a trailing `.pdf`.
- A bare id, optionally prefixed `arXiv:`.

An id is new style, `1706.03762` (four digits, a dot, four or five digits), or old style,
`hep-th/9901001` or `math.GT/0309136` (an archive, optionally a dot and a subject class, a slash and
seven digits). An old-style id keeps its slash everywhere below.

Strip the version and any `.pdf` to get `<id>`. The entry always tracks the latest version; if the
argument named an older one, say so.

## Tools

| Tool        | Needed for                       | Check                  | Install                                                   |
|-------------|----------------------------------|------------------------|-----------------------------------------------------------|
| `curl`      | every fetch                      | `command -v curl`      | preinstalled on macOS; `apt install curl`                 |
| `python3`   | the cleanup after arxiv2md       | `command -v python3`   | `xcode-select --install` on macOS; `apt install python3`  |
| `pdftotext` | only a paper with no arXiv HTML  | `command -v pdftotext` | `brew install poppler`; `apt install poppler-utils`       |

A missing `pdftotext` does not stop a run on its own. Offer the install, and if it is declined,
continue; the run stops only if the paper turns out to need the fallback. A missing `python3` stops
the run before any fetch, since every arxiv2md result goes through the cleanup: offer the install,
and if it is declined, stop.

## Identity

- `canonical` is `arxiv:<id>`, without a version: `arxiv:1706.03762`, `arxiv:hep-th/9901001`.
- `url` is `https://arxiv.org/abs/<id>`, without a version.

## Metadata

Fetch the Atom feed from the arXiv API into the scratchpad:

```
curl -fsS -o <scratchpad>/arxiv-meta.xml "https://export.arxiv.org/api/query?id_list=<id>"
```

`opensearch:totalResults` of `0` means arXiv has no such paper; stop. An `entry` whose `id` is under
`http://arxiv.org/api/errors` is arXiv saying the id is malformed; stop and quote its `summary`.
Otherwise read the one `entry`:

| meta.yaml   | From the entry                                                                  |
|-------------|---------------------------------------------------------------------------------|
| `title`     | `title`, with newlines and runs of spaces collapsed to one space                |
| `version`   | the `v<N>` suffix of `id`, such as `http://arxiv.org/abs/1706.03762v7`          |
| `published` | the date part of `published`, which is the first version's date                 |

`summary` in the feed is the abstract. It is not the entry's summary, which is written from
`source.md`. The `link` with `title="pdf"` is the PDF of the latest version, used by the fallback.
arxiv2md's own front matter is not used: its authors are noisy and it has no dates.

## Content

First ask arXiv whether the paper has an HTML rendering, saving the page into the scratchpad for the
cleanup:

```
curl -sSL -o <scratchpad>/arxiv-page.html -w '%{http_code}' https://arxiv.org/html/<id>
```

`200` means arxiv2md can convert it. `404` means it cannot; go straight to the fallback without
calling arxiv2md. Anything else is a failure.

### arxiv2md

```
curl -sS -o <build>/source.md -w '%{http_code}' \
  "https://arxiv2md.org/api/markdown?url=<id>&remove_refs=false&remove_citations=false"
```

URL-encode the id, so an old-style id's slash is `%2F`: `url=hep-th%2F9901001`. Both options must be
`false`: the defaults, `true`, drop the reference list and cut the inline citations out of the
middle of sentences. Leave `remove_toc` and `frontmatter` at their defaults. The site's other pages,
such as `https://arxiv2md.org/abs/<id>`, are its web UI and return HTML, not markdown.

- `200` with a body that starts at the paper, usually `## Abstract`, is the result. Run the cleanup
  below over it, set `converter: arxiv2md+cleanup` and keep no `raw/`.
- `200` with a body holding `## Submission history` and `# arXivLabs` is arXiv's abstract page
  scraped as markdown, which is what arxiv2md returns for a paper with no HTML. Treat it as `404`
  above and use the fallback.
- `400` has a one-line body starting `Error:`. Quote it to the user and use the fallback.
- `429` means the rate limit, 30 requests a minute. Stop and say to run it again in a minute.
- Anything else is a failure.

### Cleanup

arxiv2md leaves marks of the conversion in the text: a doubled `Abstract`, `- •` list items,
footnotes inlined as `(^1^1 1 ...)`, display math wrapped twice, doubled inline math in the abstract
and figures as `Figure:` and `Refer to caption:` lines. Undo them with the skill's script, which
rewrites the file in place and reads the page the HTML check saved:

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/research/scripts/cleanup.py" \
  --html <scratchpad>/arxiv-page.html --page-url https://arxiv.org/html/<id>v<N> \
  "<build>/source.md" "<build>/source.md"
```

`<id>v<N>` is the version from the metadata, never a value read from the page, and the URL has no
trailing slash, since the page's image paths resolve against it. arxiv2md gives a figure an image
only when the page holds a plain `<img>` for it, takes only the first panel, and writes a URL that
does not resolve; the page lets the script do better:

- A figure arXiv hosts as image or SVG files becomes one image per panel, taken from the page,
  followed by its caption.
- A drawing LaTeXML wrote inline, which renders only inside arXiv's page, becomes its caption
  followed by a link to the figure there, `[Figure N on arXiv](https://arxiv.org/html/<id>v<N>#<figure id>)`.
  An image arxiv2md took from inside the drawing, such as a model's logo, is dropped.
- A figure the script cannot match keeps what arxiv2md wrote, except that a bare `Figure:` line
  becomes the caption without the prefix.

The images are remote `https` images on arXiv, so nothing is downloaded and there is still no
`raw/`. Pass `--html` and `--page-url` only when the HTML check returned `200`, since curl writes
the file whatever the status; without them the script changes no figure beyond the `Figure:` and
`Refer to caption:` pairs.

A non-zero exit is a failure. Do not edit `source.md` by hand to finish what the script leaves:
multi-row table headers that spill into body rows stay as arxiv2md wrote them.
`scripts/README.md` lists what the script changes.

### The PDF fallback

```
mkdir -p <build>/raw
curl -fsSL -o <build>/raw/paper.pdf https://arxiv.org/pdf/<id>v<N>
pdftotext -enc UTF-8 <build>/raw/paper.pdf <build>/source.md
wc -c < <build>/raw/paper.pdf
```

`<id>v<N>` is the version from the metadata. Set `converter: pdftotext` and `lossy: true`: the text
has no headings, equations are flattened, and running headers and footnotes fall into the body.
Keep the PDF in `raw/`, unless it is over 20971520 bytes, the 20 MB a file of an entry may hold:
then `rm '<build>/raw/paper.pdf'`, with the literal path typed in single quotes, never a shell
variable, keep `source.md`, and say in the closing message the PDF was too large.
