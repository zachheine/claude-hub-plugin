---
name: dispatch
description: RETIRED in plugin 4.0. The standing dispatcher session is no longer used; hubs start spokes themselves with the built-in start-session tool and run bookkeeping through the `books` skill. Use only when a session that was a dispatcher is told to reload this skill, or when the user says "dispatch", "dispatcher", "check the queue", or asks what happened to the dispatcher.
---

# Dispatcher: retired

Plugin 4.0 retired the dispatcher. Why, in short:

- **Spawning moved to the hub.** The app's start-session tool sets a spoke's model, effort, permission mode and worktree at launch, so the two-turn model handshake is gone. And the app refuses to start a session on a turn that another session's message began, which is every dispatcher turn: a dispatcher can only post cards, not start spokes.
- **The books moved to the `books` skill**, which the hub runs as a cheap fresh subagent after each merge train, so no standing session or queue is needed.
- **The daily hours report** was always its own scheduled task; it now lives in the `books` skill too.
- **Broadcasts to hubs** are sent by the hub directly.

## If you are a dispatcher session reading this

1. Do not spawn, do not process the queue, and do not do the books.
2. List `~/.claude/dispatch/<repo>/queue/`. If any file is waiting, name each one (title and model line) in your reply; the hub will start those spokes itself.
3. Reply to the hub, or to the user if no hub is open, in one line: "Dispatcher retired (plugin 4.0); <n> queued briefs left: <titles or none>."
4. Then archive this session with the session-management archive tool on `"self"`. Do not ask the user; retiring dispatchers was the user's decision (2026-11-25).

## If the user asks for something a dispatcher used to do

- "check the queue" or a spawn: tell them the hub starts spokes now, and point them at the repo's hub session.
- "do the books", "clean up now", "hours report", "reconcile hours": invoke the `books` skill.
- "broadcast to hubs": the hub sends it directly (hub skill, Rules).

The old script path `skills/dispatch/scripts/hours-report.py` is a shim that runs `skills/books/scripts/hours-report.py`; point anything that still names the old path at the new one.
