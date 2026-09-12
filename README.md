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
- **dispatch**: a tiny second session, pinned to the model you want spokes to run on. Chip-spawned sessions inherit the model of the session that spawns them, so a Fable hub sends briefs to an Opus dispatcher and every spoke comes out on Opus with nobody touching a picker. Say "act as dispatcher" in a fresh session in the primary checkout.

## Assumptions

Written for the Claude desktop app (Code tab), where spoke sessions are launched from spawn-task chips. It works from the CLI too: the hub hands you each brief to paste into a session you start with `claude --worktree`.

## Layout

```
.claude-plugin/plugin.json        plugin manifest
.claude-plugin/marketplace.json   this repo is its own marketplace
skills/hub/SKILL.md               the hub skill
skills/dispatch/SKILL.md          the dispatcher skill
```
