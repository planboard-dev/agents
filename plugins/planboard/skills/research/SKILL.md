---
name: research
description: >
  Fetch a paper, talk or article into a Planboard root's research library as Research/<slug>/: the
  content converted to markdown in source.md, what the conversion started from in raw/, and a
  meta.yaml with where it came from, tags reused from the library, and a summary. Each kind of
  source has a handler of its own; arxiv is the first. Ingesting the same source again updates the
  entry in place. Invoke it explicitly, by typing /planboard:research <url> or by naming the skill.
  It does not start on its own when a link comes up in conversation.
argument-hint: <url or path>
---

# Research library ingest

Only run this skill when the user types `/planboard:research <url>`, or `<path>` for a local file, or
names the skill. Otherwise, do not start it.

Look for `mcp__planboard__whoami` among the loaded and deferred tools.

With it, load `mcp__planboard__whoami`, `mcp__planboard__guide`, `mcp__planboard__api_check`,
`mcp__planboard__api_read`, `mcp__planboard__query_research`, `mcp__planboard__query_tags`,
`mcp__planboard__upload` and `mcp__planboard__api_research_put` with ToolSearch, call `whoami` and
check its Level. This skill needs planboard API level 2. Below that, say the server's binary needs
upgrading and stop. If a tool cannot be loaded or the call fails, stop and say so, and do not use
the CLI, since that could write to a local root. Then use the `guide` tool, and read its `tools`
topic first.

Without it, run `claude mcp get planboard`:

- A server configured with no tools: stop and say so, since falling back could write to a local root.
- It reports no such server: use the CLI, with `planboard guide <topic>`.
- Any other failure: stop and say so.

On the CLI, a Level below 2 from `planboard api version`, or a failure of that command, means the
binary needs upgrading. Say so and stop.

Fetch the `index` and the `research` topic. An index that lists no `research` means the binary needs
upgrading: say so and stop. Any other failed fetch stops the run: say what failed.

## Kinds

Work out the kind from the argument with this table, then read that handler's file. The handler says
how to recognize its URLs in detail, which tools it needs, how to get the identity, the metadata and
the content, and what counts as a failure.

| Kind      | Recognized by                                                   | Handler                  |
|-----------|-----------------------------------------------------------------|--------------------------|
| `arxiv`   | an `arxiv.org` URL, or a bare arXiv id such as `1706.03762`     | `references/arxiv.md`    |
| `youtube` | a `youtube.com`, `youtube-nocookie.com` or `youtu.be` URL; the handler turns down any that names no single video | `references/youtube.md` |
| `local`   | a path starting `/`, `~/`, `./` or `../`, or a `file:` URL; the handler takes a PDF, markdown or HTML file | `references/local.md` |
| `article` | any other `http` or `https` URL                                 | `references/article.md`  |

The Handler column is a path under `${CLAUDE_PLUGIN_ROOT}/skills/research/`. The rows are tried in
order and the first that matches wins, so `article` takes only what no row above it claims. An
argument no row matches, such as a bare word, is not handled: say which kinds are handled and stop.
A new kind is a new handler file and one row here, above `article`.

Then follow the `research` topic with that handler, and fetch it again once its result is gone.
