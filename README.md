# Planboard agents

The Claude Code plugin for [Planboard](https://planboard.dev).

```
claude plugin marketplace add planboard-dev/agents
claude plugin install planboard@planboard
```

Auto-update is off by default for this marketplace, so fetch a newer release with:

```
claude plugin marketplace update planboard
claude plugin update planboard
```

The skill is then available as `/planboard:planboard`, and also as `/planboard` as long as no other
skill uses that name. The same plugin provides `/planboard:research <url or path>`.

This repository is generated from the Planboard release.
