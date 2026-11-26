---
name: planboard
description: >
  Run a Planboard idea discussion or design interview and maintain a Planboard planning tree:
  project.md, discussion.md, interview.md, items/<slug>.md and plans/. Covers the idea discussion
  of a topic with nothing decided, the interview that creates a project or a program, and the
  lifecycle rules that follow it, such as marking an item active, recording the outcome when it
  lands, retiring it with a reason, and updating the sequence after an insert. Also covers running
  the sequence: a worktree for the run, a build agent and a review agent per item, and a commit
  prompt before the item is closed. Also writes slide decks about a project, for a talk or a
  stakeholder briefing, as presentations/<deck>/presentation.md: a short interview about the talk,
  a deck in the planboard theme with speaker notes, checked before it is handed over. Invoke it
  explicitly, by typing /planboard or by naming the skill. It does not start on its own during
  planning discussion.
---

# Planboard

Start only when the user types `/planboard` or names the skill.

Look for `mcp__planboard__whoami` among the loaded and deferred tools, and load it and
`mcp__planboard__guide` with ToolSearch.

With it, call `whoami` and check its Level. This skill needs planboard API level 2. Below that, say
the server's binary needs upgrading and stop. If the call fails, stop and say so, and do not use the
CLI, since that could write to a local root. State `whoami`'s root and mode to the user. Then use
the `guide` tool.

Without it, run `claude mcp get planboard`:

- A server configured with no tools: stop and say so, since falling back could write to a local root.
- It reports no such server: use the CLI, with `planboard guide <topic>`.
- Any other failure: stop and say so.

On the CLI, a failed `planboard guide index`, or a Level below 2 from `planboard api version`, means
the binary needs upgrading. Say so and stop. Never fall back to reading or editing the files by hand.

On the tools or the CLI, a topic the work needs that the index does not list, or whose fetch fails,
such as `presentation` when the user asks for a slide deck, also means the binary needs upgrading.
Say so and stop, and never write the files by hand.

Fetch the `index`, and `tools` first when you are on the tools. Fetch each phase's topic at that
phase, and again when its result is gone. Follow the rules there.
