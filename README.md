# hub

A Claude Code skill for running one session as the **hub** of a hub-and-spoke workflow: the hub scopes work, writes self-contained briefs, fences files between parallel work items, spawns **spoke** sessions in git worktrees, and reviews and merges their PRs. It stays on the default branch and never builds features itself.

The skill carries measured, non-obvious facts about the setup: which model spoke sessions actually inherit, why spokes prompt for permissions even with a good allow-list, what a fresh worktree is missing, and how dev servers in a worktree silently serve the wrong code.

## Install

In Claude Code:

```
/plugin marketplace add zachheine/claude-hub-plugin
/plugin install hub@claude-hub-plugin
```

Then in any repo, say "act as hub" or "be my hub" to start.

## Skills

- **hub**: the coordinating session. Stays on the default branch, scopes work, writes self-contained briefs, fences files between parallel spokes, and reviews and merges PRs.
- **dispatch**: the standing Opus session beside the hub. It spawns every spoke, because chip-spawned sessions inherit the model of the session that spawns them, so a Fable hub gets Opus spokes with nobody touching a picker. After each merge train it also keeps the books: pulls main, removes merged clean worktrees, regenerates the changelog if the repo has one, ticks scoping-doc checkboxes, and settles the user's hours from an attention estimate (`skills/dispatch/scripts/attention.py`, derived from typed messages in local transcripts and labelled as such). The hub opens it with a chip and sets its model.
- **changelog**: a changelog derived from git history rather than written by hand. A zero-dependency Node generator walks the default branch's first-parent line, classifies each commit by what its diff touched, and writes a committed JSON payload; `--check` is a CI gate that re-derives every entry from its own commit and fails on drift, but never merely because newer commits exist. Ships a static reference page and an example classifier config. The dispatcher runs the generator when it keeps the books.

## Layout

```
.claude-plugin/plugin.json        plugin manifest
.claude-plugin/marketplace.json   this repo is its own marketplace
skills/hub/SKILL.md               the hub skill
skills/dispatch/SKILL.md          the dispatcher skill
skills/dispatch/scripts/attention.py   attention-time estimate from local transcripts
skills/changelog/SKILL.md         the changelog skill, its generator and a static page
```
