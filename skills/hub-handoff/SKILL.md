---
name: hub-handoff
description: Move a repo's hub role from one session to a fresh one without losing in-flight work — the old hub flushes its board and writes a handoff note, retires itself, and forwards stragglers; the new hub picks up the note, announces itself to every spoke, and archives the old hub once its spokes have wrapped. Use when the user says "hub handoff", "hand off the hub", "move to a new hub", "fresh hub", "retire this hub", "this hub is bloated", or is moving a hub to another machine or account. Not needed to switch between two different repos' hubs.
---

# Hub handoff

A hub's conversation is not the record. The board in memory, open PRs, worktrees and linked sessions are, and a fresh `/hub` already rebuilds from them. A plain switch still loses three things, and this skill exists for them:

- **Whatever never reached the board**: a half-drafted brief, a decision the user made two messages ago, the next step the old hub was about to take.
- **Routing.** Spokes report to the hub that started them (`"parent"`), and the app wakes that hub when they end a turn. Neither can be moved to another session.
- **Merges.** Two live hubs can both think they own main and run trains over each other.

**Switching between two repos' hubs needs no handoff:** each hub owns only its repo. This skill is for replacing the hub of one repo.

## Decide where the note goes

- **Same machine, same account** (the usual case: the old hub is bloated or compacted too often): `~/.claude/dispatch/<repo>/handoff.md`, plus the board in memory.
- **Another machine or another account:** memory, linked sessions and `~/.claude` do not travel. Commit the note as `HUB-HANDOFF.md` at the repo root on the default branch (a direct docs commit) and push. It must contain nothing that cannot be on GitHub: no secrets, no client data.

## In the old hub

1. **Flush.** Bring the board up to date: every in-flight spoke (name, `local_...` session id, branch, PR, fence, state: building, PR open, awaiting merge, wrapping), decisions taken since the last board write, standing directions the user gave this session, open questions waiting on the user, and the next action you were about to take.
2. **Write the handoff note** where the step above says, in this shape:

   ```
   # Hub handoff: <repo>
   from: <this session's local_... id>   at: <ISO time>
   dial: <heavy | light>
   ## In-flight spokes
   - <name> <local_id> <branch> <PR or none> <state> fence: <files>
   ## Decisions since the board was last written
   ## Standing directions from the user
   ## Waiting on the user
   ## Next action
   ```
3. **Retire.** Rename this session `Retired hub - <repo>` with the session-management rename tool on `"self"`. From now on, **refuse merges and starts** in this session until the user invokes `/hub` here again; reply "This hub is retired; the hub for <repo> is <new hub, or 'the session you open next'>."
4. **Tell the user** in two lines: open a new session in the primary checkout and run `/hub`; keep this one open until the new hub archives it. **The user opens the new hub, not you.** A session you start with the start-session tool becomes your side session, so archiving you later would archive it too, and a session started by Claude's own tools cannot turn on auto-memory (Claude Code 2.1.285), which a hub needs for its board. Do not use the built-in hand-off tool either: it forks this conversation, which is the bloat the handoff is meant to shed.
5. **While retired, forward.** When a spoke messages you, or the app wakes you with a spoke's turn-end note, send the new hub one line: "forwarded from <spoke name>: <the gist>". Do nothing else with it.

## In the new hub

`/hub` finds the note on invocation and sends you here first.

1. **Read the note**, then establish ground truth as the hub skill says. Where the note and ground truth disagree, ground truth wins; say so on the board.
2. **Copy the note into the board** in memory, so it survives this session's own compaction.
3. **Announce yourself.** Send the retired hub "I am the new hub for <repo>: <your local_... id>. Forward spoke messages here." Send each in-flight spoke "The hub for <repo> is now session <your local_... id>. Send PR-ready and wrapped messages there, not to parent." Spokes the old hub started stay linked to it; the app keeps waking it, and it forwards.
4. **Delete the note** so it cannot be picked up twice: `rm ~/.claude/dispatch/<repo>/handoff.md`, or for `HUB-HANDOFF.md` a commit `docs: hub handoff picked up` that removes it, pushed.
5. **Archive the retired hub once every spoke it started has wrapped**, with the session-management archive tool; do not ask the user (spoke and hub retirement are standing decisions). Before then, archiving it would archive its finished side sessions, which includes spokes idle while they wait for their merge, and they would lose their exit pass. Put "retired hub <id>: archive after <spoke names> wrap" on the board.
6. Tell the user in one line that the handoff is done and what is in flight.

## Cross-account and cloud limits

- A hub in another account cannot see this machine's sessions, linked sessions, memory, or `~/.claude`, and the two hubs cannot message each other, so the old hub cannot forward. Only the committed note and GitHub cross. Either let in-flight spokes merge and wrap before handing off, or split ownership: the old hub keeps merging and retiring the spokes it started (list them in the note under "Staying with the old hub"), and the new hub takes only new work and must not merge those PRs. The old hub renames itself `Retired hub - <repo>` only when its last spoke has wrapped.
- A cloud spoke cannot message any hub. Its PR is the only channel, so nothing about it needs moving.
