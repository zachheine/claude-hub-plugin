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
- **books**: the mechanical follow-through after a merge train, run by a fresh Sonnet subagent the hub starts, so its output stays out of the hub's context: pulls main, counts straggler sessions and worktrees, records an unconfirmed attention estimate (`skills/books/scripts/attention.py`, derived from typed messages in local transcripts and labelled as such), regenerates the changelog, and ticks scoping-doc checkboxes. Also the explicit "clean up now" pass and the daily cross-repo hours report, which a scheduled task runs and which posts to Superstudio when `~/.claude/dispatch/ingest.token` exists.
- **hub-handoff**: move a repo's hub role to a fresh session (bloat, another machine, another account) without losing in-flight spokes, routing, or merge ownership.
- **dispatch**: retired in 4.0. Hubs now start spokes with the app's start-session tool, which sets model and effort at launch, and the books skill took the bookkeeping. The stub tells any still-running dispatcher to stand down.
- **one-by-one**: ask the user questions one at a time instead of as a list. Numbered backlog, one question per message, skip / later / you-decide, a decisions summary at the end. Hubs use it for their "waiting on you" lists.
- **changelog**: a changelog derived from git history rather than written by hand. A zero-dependency Node generator walks the default branch's first-parent line, classifies each commit by what its diff touched, and writes a committed JSON payload; `--check` is a CI gate that re-derives every entry from its own commit and fails on drift, but never merely because newer commits exist. Ships a static reference page and an example classifier config. The books skill runs the generator after each merge train.

## Keeping running sessions current

Skill updates do not reach a session that already loaded the skill. Rather than broadcasting by message, which is capped at ten sends per turn and refused by a blocked session, the plugin ships a `UserPromptSubmit` hook. It hashes the installed skill files on every prompt, prints nothing when nothing changed, and prints one line when a skill changed since that session last saw it, telling the session to re-invoke the skill it runs. Zero cost at rest. Installed with the plugin via `hooks/hooks.json`; if you run the skills from `~/.claude/skills/` instead, copy `hooks/skill-change-notice.sh` to `~/.claude/hooks/` and add it as a `UserPromptSubmit` hook in `~/.claude/settings.json`.

## Layout

```
.claude-plugin/plugin.json        plugin manifest
.claude-plugin/marketplace.json   this repo is its own marketplace
skills/hub/SKILL.md               the hub skill
skills/books/SKILL.md             the books skill
skills/books/scripts/attention.py   attention-time estimate from local transcripts
skills/books/scripts/hours-report.py daily cross-repo hours report and confirmation, posted to Superstudio when `~/.claude/dispatch/ingest.token` exists
skills/hub-handoff/SKILL.md       move the hub role to a fresh session
skills/dispatch/                  retired stub, plus a shim at the old hours-report path
skills/one-by-one/SKILL.md        ask questions one at a time
skills/changelog/SKILL.md         the changelog skill, its generator and a static page
docs/changelog.json + docs/index.html   this repo's own derived changelog
hooks/skill-change-notice.sh      UserPromptSubmit hook: one-line notice when a skill changed on disk
```
