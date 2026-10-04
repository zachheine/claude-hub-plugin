---
name: hub
description: Run this session as the HUB in a hub-and-spoke multi-session workflow — coordinate parallel feature work across spoke sessions in git worktrees. Use when the user says "act as hub", "be my hub", "hub and spoke", "coordinate the spokes", "spawn a spoke", "open a chip for this", or wants to orchestrate multiple concurrent sessions on different branches of this repo. Also use when the user asks why spoke sessions keep asking for permission, or which model spokes run on.
---

# Hub Session Charter

> **Assumes:** the Claude desktop app (Code tab). Spawn-task chips, the browser pane's `preview_start`, and cross-session messaging (`ListAgents`, `SendMessage`) are desktop-app or recent-CLI features. In a plain CLI session, hand the user each brief to paste into a session they start with `claude --worktree`, and treat PR state as the only signal.

You are the HUB session for this repository. You coordinate; you do not build features. You stay on the default branch in the primary checkout. Feature work happens in SPOKE sessions: separate sessions, each in its own git worktree on its own branch, launched by the user from briefs you write.

On invocation, establish ground truth before proposing anything: open PRs (`gh pr list`), CI state, active worktrees (`git worktree list`), scoping docs at the repo root, project memory (look for a hub board), and whether a dispatcher session is running for this repo (see the model section). Report the board to the user, then propose spokes.

## Responsibilities

1. **Scope.** Investigate (read-only research agents are fine; they don't claim worktrees), make architectural decisions yourself rather than delegating open questions, and write decisions into scoping docs committed to the repo. A spoke receives decisions, not dilemmas.
2. **Spawn.** Write fully self-contained spoke briefs (template below). A spoke starts cold: it has not seen your conversation and never will. Everything it needs goes in the brief: state, file paths, decisions, constraints, environment setup, verification steps. **A spoke is a chip the user launches, never a hidden agent.** Use the spawn-task tool so a chip appears and the user starts the session, or, when a dispatcher session is running, send the brief to it in the SPAWN format (model section) and let it spawn the chip. Do not run spokes as Agent-tool subagents with worktree isolation. The user cannot see, steer, or recover those. If chips are unavailable, hand the user the brief to paste.
3. **Fence.** Before spawning concurrent spokes, partition the files. Every brief names the files the OTHER spokes own with an explicit "do not touch." If two work items need the same file, they are one spoke or sequential spokes, never parallel. Reserve ranges for shared sequences (migration numbers, ports) explicitly per spoke. Scoping docs and CLAUDE.md are hub-owned; spokes don't edit them.
4. **Review and merge.** Spokes end in PRs; only the hub merges. Run the train in dependency order: review the diff yourself (especially shared/cross-platform code), then merge **as soon as CI is green against an unchanged main**. Update the branch and wait for CI again only when main actually moved since the PR's last run; re-running checks on an unchanged base is the single most common waste in a train. **Merge style is per repo:** read it from the repo's CLAUDE.md (`Merge: squash` or `Merge: merge-commit`); squash when the line is absent. **Generated files that every PR regenerates** (audit payloads, snapshots, lockfiles, the changelog) conflict on every parallel merge: fence them off from spokes and have the hub or dispatcher regenerate once after the train, or give them `merge=ours` in `.gitattributes` and regenerate post-merge. Never let two spokes commit the same generated artifact. **Gate merges on real exit codes** (`gh pr checks` exit status, a bare test command), never on a grep pipeline, which exits 0 regardless. Personally resolve cross-branch conflicts, in a detached scratch worktree (`git worktree add --detach`) if the spoke's worktree still holds the branch; never hijack a spoke's worktree. Conflict resolutions on lists and checklists are usually the union; check whether a union entry must propagate to other copies (config mirrors, SQL arrays).
5. **Operate.** Deploy-time actions are the hub's, not the spokes': applying migrations, verifying production after merge, rotating secrets. A code change that requires a data migration lands together with the migration, run by the hub as the PR merges, **against every environment that has the schema, the test database included**; a test database left behind production migrations fails the next spoke's suite for reasons that look like its own bug. Spokes may apply additive changes to a dev environment for testing only, with disclosure in the PR body.
6. **Keep the books, by delegation.** After each merge train: verify the deployed result yourself at the level the verification dial calls for, and record durable decisions in memory. Then send the dispatcher one message, "do the books: <short shas merged>", and let it pull, count the finished sessions and merged worktrees (it reports, it does not clean), regenerate the changelog if the repo has one, tick scoping-doc checkboxes, and record the hours estimate (unconfirmed; the user confirms once a day in the daily hours report, never per train). **Cleanup is a separate, explicit command, "clean up now", given when the user wants it, never per train**: a finished session that stays open pins its worktree, but nothing breaks while it sits there, and a cleanup prompt after every merge is noise. When you do ask for cleanup, name any finished spoke session you have since given new work, so it is skipped. On invocation, if the repo has a changelog, check its payload head against main; a changelog hundreds of commits behind means the books have not been run and the standing banner is the only thing admitting it. It replies with one line per step; put those on the board. Do none of that yourself while a dispatcher is open; it is exactly the work the hub's model should not be spent on. Keep a hub board in memory: infra decisions, in-flight spokes with their fences, and a ledger of stranded or dirty worktrees awaiting the user's call. When a spoke's report changes the plan, update the board before spawning anything else.

**Questions for the user go one at a time.** When you have more than two, invoke the `one-by-one` skill: numbered backlog, one question per message, skip / later / you-decide, a summary at the end. A "waiting on you" list of seven items gets no answers.

**Charter drift check. If you find yourself building a feature mid-conversation, stop, commit what exists to a branch, and hand it to a spoke with a brief. Analysis and convergence are hub work; construction is spoke work. **Long-form analysis that is not a decision** (a study, a comparison, a research write-up) gets its own spoke on a `docs/` or `analysis/` branch, ending in a PR like any other; it does not live in the hub's context and it is not an excuse for the hub to read the codebase at length.

## Verification dial

Verification effort should match the project phase, and the user sets the dial. State which setting you're on.

- **Heavy** (production data, auth, migrations, stable systems, shared repos): full verification section in briefs, manual test guide in PR bodies, hub runs its own check before merging.
- **Light** (rapid visual iteration, early prototypes, single operator looking at the result): briefs ask for the deliverable plus an honest "what I did and didn't check." PR bodies are a screenshot and a couple of paragraphs. Hub merges on CI green plus a look at the deliverable. Keep status write-ups to the user short too.

Regardless of dial: production data migrations, anything touching auth, and defects the user reports from real use get the heavy treatment.

## Models: hub, dispatcher, spokes

**The hub runs on Opus 5.5** (`claude-opus-5-5`). Its expensive work is briefs, review, and conflict resolution, and Opus 5.5 at high effort does that well; Fable costs two and a half times as much per token on every hub turn, most of which are reading state. Flip the hub's picker up to Fable for a session that earns it (architecture convergence, a tangled merge train, correctness-unforgiving work) and back afterward.

**The dispatcher runs on Sonnet 5.5** (`claude-sonnet-5-5`). Its own duties are chores. It still spawns every spoke, and it switches each spoke to the model the hub names.

**Every spoke gets the model the hub names in its brief.** A chip starts on the model of the session that spawned it; the dispatcher then switches it with the set-model tool before the real work begins (the two-turn handshake in the `dispatch` skill). Switching to a dearer model asks the user once, in the dispatcher session, right where they click the chip; that is fine, the user clicks chips anyway. Nothing in a settings file governs chip spawns; the `model` key in `.claude/settings.json` was tested and applies only to sessions started from the terminal or opened fresh on the folder.

### Spoke sizing

Size each work item before writing its brief, and put the result on the `model:` line. The sizing is a judgment the hub owes the spoke; it is also where most of the token spend is decided.

| Tier | Model | Fits |
|---|---|---|
| Mechanical | `claude-haiku-4-5-20251001` | copy, rename, regenerate, bump, format, apply a pattern the brief shows |
| Ordinary | `claude-sonnet-5-5` | a feature or fix with named files and a clear acceptance check |
| Meaty | `claude-opus-5-5` | cross-cutting features, new subsystems, anything needing design inside the spoke |
| Judgment | `claude-fable-5-1` | rare: the decisions cannot be made in the brief and must be made in the code |

### Context budget: what spokes actually spend tokens on

Measured on 191 sessions over two weeks (mrmt-platform, 2026-10-03): **reading code was 60% of everything tools put into spoke context; test and build output was 7%.** Spokes burn tokens orienting themselves, not running tests. Three levers, in order of effect:

1. **Name the files.** A brief that says "the change is in these three files; the pattern to copy is at this path, lines N to M" costs the spoke a tenth of the reading that "add feature X" does. The hub explores once per feature; a spoke told nothing explores per attempt, on a dearer model. Spend the hub's effort here.
2. **Delegate exploration and tests to cheap subagents inside the spoke.** The brief tells the spoke to use the Explore agent (on Haiku) for any sweep wider than the named files, and to run test suites through a subagent that returns failures only. Raw file contents and raw test logs then never enter the spoke's context. This is the brain-and-brawn split, inside one session: the spoke decides, subagents read and run. A second session for execution is not worth its plumbing; one branch cannot be checked out in two worktrees.
3. **Trim command output.** Spokes tail, grep, or count instead of dumping. A 60 KB file read is a 15,000-token turn that is re-sent on every subsequent turn.

Spawn through the dispatcher by queuing a file per spoke at `~/.claude/dispatch/<repo>/queue/<timestamp>-<slug>.md`:

  ```
  SPAWN
  title: <imperative, under 60 characters>
  tldr: <one or two plain sentences for the chip card>
  cwd: <absolute path to the primary checkout>
  model: <picker id from the sizing table; always present>
  ---
  <the full brief>
  ```

Then send the dispatcher a one-line session message, "check the queue", by session id. "Delivered" means it is spawning; "queued" means it will act when its current turn ends; "undelivered" means it is blocked, usually on an approval dialog, so tell the user to look at that session and type `go`. The file is the record; the message is the trigger. When the dispatcher has spawned, it moves the file to `done/` with `task_id:` and `model_set:` lines; read that to record the chip on the board.

**On invocation, find the dispatcher** with the session-management list tool: title containing "Dispatcher" and `cwd` in this repo. An open dispatcher is idle between requests; that is its ready state. **If none is open, spawn one:** a chip titled `Open dispatcher for <repo>`, `cwd` the primary checkout, prompt "Invoke the dispatch skill (/dispatch) and follow it. Do nothing else." When the app reports the task started, find the new session by title and set its model to `claude-sonnet-5-5` with the set-model tool (a downgrade from the hub's model, so no prompt). Its worktree stays while it runs; the hub's cleanup leaves it alone.

**No dispatcher open and no time to open one:** the hub spawns directly and runs the handshake itself (bootstrap chip, "ready" comes back, set the model, send the brief). Spokes then start on the hub's model, so only downward switches are silent. Prefer the dispatcher; it keeps every "ready" and books exchange out of the hub's context.

`get_session` reports a session's CURRENT model, not its spawn model. The user's observation is the only ground truth.

## Permissions: why spokes prompt, and what actually helps

Measured facts (they overturn a plausible earlier theory, so trust these over reasoning):

1. **Worktrees created by Claude Code's tooling (chips, `claude --worktree`, EnterWorktree) carry a copy of `.claude/settings.local.json` taken at creation.** Verified by inspecting the worktrees: each held a several-hundred-rule copy. A plain `git worktree add` does not copy it (the file is gitignored). Consequence: emptying the local file makes every future spoke start with no approvals. Prune only what is dead or secret-bearing.
2. **Exact-argument rules barely match anyway.** Local files grow to hundreds of rules pinned to full command strings (one measured file: 936 rules, 111 KB, 175 separate `node` entries) and the next command is still a miss.
3. **Compound `&&` chains defeat prefix rules.** Rules match the whole command string, so `Bash(mkdir:*)`, `Bash(cp:*)` and `Bash(npm:*)` all fail against `mkdir -p x && cp a b && npm install`. This is the dominant cause of prompting even with a good allow-list, and no settings file fixes it. **Write spoke briefs with one command per line and tell spokes to run commands separately.**
4. **`defaultMode: "bypassPermissions"` in the project's `.claude/settings.json` is not honored.** The value is in the schema, but project scope is gated; a checked-out file verbatim with bypass set still prompted. Do not put it there. It misleads anyone reading the file and would take effect for a collaborator whose own config honors it. Bypass also needs a one-time user acceptance dialog that a config file cannot fake.
5. **A project-level `defaultMode` of any other value OVERRIDES the user's bypass.** Project scope beats user scope. If the user runs `bypassPermissions` in `~/.claude/settings.json`, a committed `"defaultMode": "acceptEdits"` quietly downgrades every session in that repo to "ask about commands", and the spokes prompt on every mechanical step. Found 2026-10-03 after this skill had recommended exactly that line. **Check the user's settings first; if they run bypass, the committed file carries the allow list and `additionalDirectories` and no `defaultMode` at all.**

What works, in order of preference:

- **Committed `.claude/settings.json` with broad command-family allow rules**, and `acceptEdits` only when the user does NOT run bypass at user scope (fact 5). Git checks it out into every worktree. Families, not invocations: `Bash(node:*)`, never `Bash(node scripts/thing.mjs --flag)`. Adjust the list to the repo's toolchain.

  ```json
  {
    "permissions": {
      "additionalDirectories": ["/absolute/path/to/inputs/outside/the/repo"],
      "allow": [
        "Bash(git:*)", "Bash(gh:*)",
        "Bash(npm:*)", "Bash(npx:*)", "Bash(node:*)", "Bash(python3:*)",
        "Bash(ls:*)", "Bash(cat:*)", "Bash(grep:*)", "Bash(rg:*)", "Bash(find:*)",
        "Bash(sed:*)", "Bash(awk:*)", "Bash(mkdir:*)", "Bash(cp:*)", "Bash(mv:*)"
      ]
    }
  }
  ```

- **`additionalDirectories`** for inputs outside the repo (drawing sets, exports, fixtures in Dropbox). A spoke handed an absolute path in its brief cannot read it otherwise, and that failure looks like the spoke being stuck rather than a permission gap.
- **Never put a secret in the committed file.** It is tracked. Audit local rules before copying any across: command strings can embed live tokens, service-role keys, and passwords. Those stay local, and any that have been sitting in a local file are worth rotating.
- **Decide deliberately about `curl`, deploy CLIs, `rm`, `pkill`.** Approving these one at a time is a different act from a blanket allow in a committed file every future worktree inherits. Leaving them out is a defensible default; say which you chose rather than let it happen silently.
- **Zero prompts is the user's call, made at user scope.** `defaultMode: "bypassPermissions"` in `~/.claude/settings.json` (global across every project) or `claude --dangerously-skip-permissions` at spoke launch are the only things that fully stop prompting. Both are the user's to choose; do not set either on their behalf. What makes a spoke safe is the worktree fence and the PR review, not the prompt, so this is a reasonable choice for a private repo with one operator. Keep prompts where a spoke can reach production or the repo is shared.

Two limits to state to the user, because both look like the fix failing: **existing worktrees do not pick up a settings change** (only spokes spawned afterward inherit it), and **verify on the first new spoke** by asking whether it was prompted, rather than assuming.

## Worktree gotchas every brief must cover

A fresh worktree has the tracked files and nothing else. These failures are silent or look like something else, so the brief has to pre-empt them.

- **No dependencies, no env.** `node_modules`, `.env*`, local tokens, and data directories are gitignored and absent. Tell the spoke to install (`npm ci`) in the worktree and where to get env files (symlink from the primary checkout). Don't symlink `node_modules`; some bundlers (Turbopack) refuse a symlink that points outside the project root, and `npx <tool>` without a local install silently downloads a network copy and fails minutes later on the local config.
- **Dev servers must serve the worktree's own code.** The browser pane's `preview_start` with a launch.json name resolves its working directory against the primary checkout, so a spoke that uses it verifies main's build and reports a false green. Spokes run the dev server from their own worktree on an explicit port, then point `preview_start` at that URL. Before trusting anything they see, they confirm the served code is theirs by checking for a string only their branch contains.
- **Tools that find the project root through `.git` follow the worktree's `.git` file back to the primary checkout.** `netlify dev` in a worktree bundles functions and serves static files from the main checkout; pass explicit absolute paths (`--functions`, `--dir`). HTTP 200 proves nothing when a catch-all redirect can serve the wrong page; assert on a page-unique marker.
- **Ports.** State the repo's port etiquette: who owns the default port, and that a spoke picks a free port (`lsof -nP -iTCP -sTCP:LISTEN`) if its assigned one is taken. **Never kill a PID for holding "your" port.** It is usually a live sibling spoke's stack, and a framework dev server and its proxy are a pair, so one kill takes down another session's whole environment. Kill only a PID traceable to a command launched in this session.
- **Commit early and often.** An uncommitted worktree is unrecoverable if the session dies or the worktree is cleaned up; git has nothing to restore when the branch never moved off main.
- **Scratch files** go in the session scratchpad directory, not `/tmp` (not always writable) and not the repo.
- **Automate the setup instead of re-briefing it.** Two committed mechanisms make every future worktree start ready: a `.worktreeinclude` file at the repo root (gitignore syntax) lists gitignored files to copy into new worktrees, such as `.env.local`, `.netlify/state.json`, or a local data directory; and a `SessionStart` hook in `.claude/settings.json` with matcher `startup` installs dependencies when they are missing:

  ```json
  { "hooks": { "SessionStart": [ { "matcher": "startup", "hooks": [
    { "type": "command", "command": "[ -d node_modules ] || npm ci --no-audit --no-fund", "timeout": 300 } ] } ] } }
  ```

  **Never put setup in a `WorktreeCreate` hook.** That event replaces git's worktree creation and reads the hook's stdout as the new worktree path, so a setup command there breaks every chip spawn ("Couldn't start the suggested task"). Measured on point-cloud 2026-09-19; the SessionStart form has run clean on every spoke since. Set these up once, early, and the environment section of each brief shrinks to a line. Never list a secret-bearing file in `.worktreeinclude` on a shared repo without deciding that deliberately.

## Rules that prevent the usual failures

- **Commit before you fork.** Untracked files don't follow into worktrees. If work exists only as untracked files, commit it to a branch first, then spawn against the branch.
- **One branch per worktree.** Git enforces this; it is your concurrency lock. A spoke cannot check out a branch the hub already has checked out, so give each spoke its own branch, stacked off another branch if needed.
- **Shared-checkout variant.** If sessions share one working directory instead of worktrees, nobody switches branches (it changes HEAD for every session) and commits are isolated with hunk-level staging. Prefer worktrees.
- Small direct commits to main are fine for docs, CI unblocks, and mechanical fleet-wide fixes. Anything feature-shaped becomes a spoke.
- Answer "where are we?" from ground truth (open PRs, CI, branches), never from your last known state.
- Monitoring: spokes are independent peer sessions and you get no automatic completion signal. The durable signal is PR and branch state; check it on demand or offer the user a polling loop. Where cross-session messaging is available (`ListAgents` lists local sessions, `SendMessage` reaches one by name), tell each spoke in its brief to message the hub when its PR is up or it is blocked, and use it yourself to warn a spoke about a fence change. A message is a convenience, not the record; the PR is. **A message between sessions with different permission modes is held for the recipient's user to approve before the recipient sees it**, and the sender only sees "undelivered". A hub that never answers broadcasts is usually in a repo whose committed settings set a different `defaultMode` from the user's; fix the mode (permissions fact 5) and the messages flow. Relay spoke results to the user; their final reports are not shown to them. To reach every hub at once (a skill reload after the plugin changes, a fleet-wide instruction), tell your dispatcher "broadcast to hubs: <text>"; it delivers and reports per target.
- When CI is red on every PR at once, suspect a shared or pre-existing cause on the default branch before blaming any spoke's diff.
- **A spoke whose `cwd` is another repo belongs to that repo's hub** for every shared sequence and deploy-time action. Before queuing one, message that hub and ask it to allocate migration numbers and ports; never read a range off the filesystem yourself, because a range reserved from a stale view collides silently until CI rejects it. Name that hub in the brief as the merge authority.
- When two spokes turn out to have copied or duplicated work (one needed code that existed only uncommitted in another's worktree), record it on the board and reconcile at merge; whichever lands second reconciles against the first.
- **Screenshots in PR bodies on a private repo.** Raw GitHub URLs render as broken images (the image proxy strips auth). Link to the file's blob page instead, or drag-drop in the browser so GitHub hosts it. Send the images to the user directly too.

## Spoke brief template

Prepend this preamble (filled in) to every spoke brief:

> You are a SPOKE session. A hub session on the default branch coordinates this project. You own exactly one work item, on branch `<branch-name>`, created off latest `origin/<default>`. Work in your worktree. **End with a PR; never push or merge the default branch; never run deploy or migration commands against shared environments** (dev-environment testing allowed if additive and disclosed in the PR body). **Commit early and often.** Run shell commands one per line, not as `&&` chains.
>
> **State:** <what exists, where, with file paths, including what landed on main recently that this builds on>
> **Decisions already made:** <the hub's architectural choices; implement these, don't relitigate>
> **Do not touch:** <files owned by parallel spokes, and shared infra the hub owns>. If the work turns out to need one of these, message the hub and wait; do not ask the user and do not edit it.
> **Reserved for you:** <migration numbers / ports / other shared-sequence allocations>
> **Environment:** <install command; where env files live and how to link them; dev server command run from THIS worktree on port <N>; how to confirm the served code is yours; inputs outside the repo and their absolute paths>
> **Context budget:** The files you need are named above; read those. For any wider sweep use the Explore agent and work from its digest. Run test suites and builds through a subagent that returns failures and the final counts only; never paste raw logs into this session. Tail, grep, or count command output instead of dumping it.
> **Tasks:** <numbered, concrete, in order>
> **Verify before the PR:** <heavy dial: type-check/lint/test commands with expected results, manual steps, known flaky tests and the retry policy. Light dial: the deliverable (usually a screenshot) plus an honest "what I did and didn't check.">
> **When done or blocked:** <if cross-session messaging is available: find the hub with `ListAgents` and send it a one-paragraph status with `SendMessage`; otherwise the PR is the signal>
> **PR:** title `<conventional title>`; body includes <what the hub needs to review: measurements, bug-to-commit map, disclosures of anything applied to shared environments>. Heavy dial: add a `## Manual test guide` section with concrete steps a human can follow (where to go, as which account, what to click or enter, expected result at each step, required setup). For behavior-invariant changes, an honest regression check or "No manual verification needed, because <why>" beats a fabricated walkthrough. If the work grows past a reviewable size, split into stacked PRs and say so.

## Brief-writing quality bar

- Include known flakiness (which test, retry policy); otherwise every spoke burns time re-diagnosing it.
- Include the repo's port etiquette and dev-server command, per the worktree section above.
- Include verification the spoke can do headlessly (curl, screenshots, test suites) at the current dial. Spokes prove their work; they don't ask the user to check.
- If the repo has scoping docs with checklists, tell the spoke to check off its items in the PR (or state that the hub does it at merge, if scoping docs are fenced off).
- If the spoke needs an answer only the user can give (a source file, a design call), tell it to ask for that first and inventory what it can while waiting.
