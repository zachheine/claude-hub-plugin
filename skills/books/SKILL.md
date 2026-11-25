---
name: books
description: Keep the books for a hub-and-spoke repo after a merge train — sync main, count straggler sessions and worktrees, record the hours estimate, regenerate the changelog, tick scoping-doc checkboxes — and run the daily cross-repo hours report and its Superstudio posting. Also does the explicit "clean up now" pass. Use when a hub delegates "do the books", when the user says "do the books", "clean up now", "hours report" or "reconcile hours", or when the daily hours task runs.
---

# The Books

Mechanical follow-through for a hub-and-spoke repo. Nothing here needs judgment, so it runs on a cheap model and keeps its output out of the hub's context.

**Who runs it.** Usually a fresh subagent the hub starts after a merge train (hub skill, responsibility 6), told the primary checkout's path and the short SHAs merged. The user can also invoke it directly in any session, and the daily scheduled task runs the hours report section. Plugin 4.0 retired the standing dispatcher session that used to do this; its state was always in files, so nothing moved: `~/.claude/dispatch/` (the name is historical) still holds every repo's `hours.jsonl`, the daily reports, the Superstudio token and the posting log.

You do not scope, build, review, merge, or resolve conflicts, and you never touch a spoke's worktree. If a step needs a judgment call, stop and say so in your reply; the hub decides.

## Inputs

- `<primary>`: the primary checkout's absolute path. `<repo>` is its directory name: `basename "$(dirname "$(git -C <primary> rev-parse --path-format=absolute --git-common-dir)")"`.
- `<shas>`: the short SHAs merged in this train (for the changelog commit message).
- `<since>`: the end date of the last period in `~/.claude/dispatch/<repo>/hours.jsonl`, or the date of the oldest merged SHA if the file is missing.

## After a merge train: "do the books"

Work in the primary checkout by absolute path. Run each step, in order, and report each in one line:

1. **Sync.** `git -C <primary> pull --ff-only origin <default>`. If it will not fast-forward, stop and report; the hub owns main's state.
2. **Stragglers: count, do not clean.** Spokes retire themselves after merge (they document, then archive), so this count should be near zero. List sessions with the session-management list tool and run `git -C <primary> worktree list`. Report one line: how many spoke sessions have a merged PR and are still open, and how many worktrees sit on merged branches. **A worktree at a detached HEAD with no session holding it is the app's reuse pool after an archive: do not count it, and never remove it**; the app reuses or reaps it. Do not archive, remove, or ask anything.
3. **Hours, quietly.** Run `python3 <this skill's dir>/scripts/attention.py --repo <primary> --since <since>` and append the estimate to `~/.claude/dispatch/<repo>/hours.jsonl` as one line: `{"period": ["<from>", "<to>"], "estimate_h": <n>, "confirmed_h": null, "note": "estimate, unconfirmed"}`. **Do not ask the user anything.** Confirmation happens once a day, across every repo, in the daily report. The estimate is attention time inferred from typed messages, never billable hours. Run this before the changelog step, so a generator that reads the hours log ships the current period list.
4. **Changelog.** If the repo has a generator (`npm run changelog`, a `scripts/*changelog*`, or a line in CLAUDE.md), run it and commit the regenerated payload to the default branch as one commit, `chore(changelog): regenerate after <shas>`, then push. If the payload did not change, commit nothing. If there is no generator, say so once; scaffolding one is a spoke's job.
5. **Board checkboxes.** If the repo's scoping doc has checkboxes for the merged items that the spoke did not tick, tick them in the same commit or a `docs:` commit. Do not rewrite prose.
6. **Reply** with one line per step. That reply is all the hub sees.

## "clean up now"

Only on an explicit "clean up now" from the user or the hub, never as part of the books. The hub names any finished spoke it has since re-tasked; skip those.

1. **Classify first, read-only:** every local and remote branch by PR state, each worktree's dirtiness and holding session, and whether each branch tip equals its merged PR's `headRefOid` (`gh pr view <n> --json headRefOid`). Save names and SHAs to a file under `~/.claude/dispatch/<repo>/`.
2. **Archive** each spoke session whose PR is merged, which is not running, and which has not been given new work since (its last activity is after the merge, or the hub names it): one batch with the session-management archive tool.
3. **Remove**, one visible command each, so auto mode can see every deletion (it blocks a loop whose deletions it cannot see, even over a list it just printed): for each remaining worktree whose branch is merged and whose tree is clean, first `git log origin/<default>..<branch> --oneline`; if it prints anything the branch has unpushed commits, so leave it and name it. Otherwise `git worktree remove <path>`, then `git branch -d <name>` (`-D` only when the tip equals the merged PR's head, which a squash merge requires). Remote branches of merged PRs: one `git push origin --delete <name>` each, only when the tip matches.
4. **Never** remove a dirty worktree, a worktree with a running session, the reuse pool, or the worktree you are running in. Unmerged branches with no PR are never yours to delete: list them with a recommendation each (revive as a brief, keep as reference, delete) for the hub to put to the user one at a time.
5. Report what you archived, removed, and left, each with the reason.

## The daily hours report

A scheduled task runs `python3 <this skill's dir>/scripts/hours-report.py --completed` at 4:30 each morning. A **waking day** runs from 04:00 to 04:00, so work at 1 a.m. belongs to the evening it continued from; `--completed` reports the waking day that just ended. The script estimates attention time per repo across every repo under the user's projects folder, merges confirmations already recorded, writes `~/.claude/dispatch/reports/<date>.md`, and prints it. The task's session shows the report and asks **one** question: confirm as is, or name the repos to correct with their hours. The answer is recorded with `hours-report.py --confirm --date <date> repo=ok repo=2.5 ...`, one line per repo in that repo's `hours.jsonl`, each stamped with `confirmed_at` (UTC). If the user does not answer, the estimates stand unconfirmed and the next report lists them. When the user says "hours report" or "reconcile hours", run the same script for the day they name and handle the one question the same way.

**Posting to Superstudio.** After it writes the report, and again right after `--confirm`, the script POSTs that waking day to Superstudio's time-signals ingest (contract v1, one call per day): per repo, the folder name, the estimate, the confirmed hours or `null`, the merged attention windows clipped to the 04:00 to 04:00 day, message and session counts, and the numbers of PRs the user authored that were created or merged that day. **No titles, branch names or message text are sent.** It also posts any day in the last 35 with a report but no successful post, or confirmed since its last post, so a missed morning catches up. The token comes from `~/.claude/dispatch/ingest.token` (one line, created in Superstudio under Settings → Claude Code time, shown once, **mode 0600**); with no such file the script skips posting silently, and with a looser mode it prints one `chmod 600` line and skips without reading the file. The token is never printed, logged or put in an environment variable. Every attempt is one JSON line in `~/.claude/dispatch/ingest-posted.jsonl` (day, time, HTTP status or `"error"`, counts, and the repo keys the server reported as unmapped). A failed post never changes the exit code; the next run retries it. `--dry-run` prints the payload and sends nothing (no token needed, no report written), `--no-post` skips posting, `--post-day YYYY-MM-DD` posts one day without a report.

**Unmapped keys** in a reply mean Superstudio has no project for that repo folder name. Mapping is done on Superstudio's side; after it is mapped, `--post-day` re-posts the affected days (the ingest is idempotent).

Details that explain odd-looking behavior: a confirmed value that rounds to `0.00` is sent as `0.01`, because the server reads `0` as "dismissed". "Confirmed since its last post" compares each confirmation's `confirmed_at` with the day's last successful post; confirmation lines written before plugin 4.0 have no `confirmed_at` and fall back to their file's modification time, so an unrelated append can cause a harmless re-post of those older days. The server fixes the waking day at 04:00 to 04:00, so a custom `--day-start` makes every payload fail validation: the script prints one line and sends nothing. The endpoint must be https (plain http only to localhost) and redirects are never followed, so the token cannot travel in the clear or to another host. A network error, timeout or 5xx is retried once; 401, 403 and 422 are not, and a 401, 403 or network error stops the catch-up so one bad token costs one call, not 35. Over the caps (100 repos, 500 windows a row, 2,000 in all) the script keeps the top 100 repos by estimate and widens `--window` for that post only, saying so in one line.

## Rules

- Never kill a process for holding a port; it is usually a live spoke.
- Never force-push, merge, or commit anything to main beyond the changelog and checkbox commits above.
- Everything this skill owns is in files: `~/.claude/dispatch/<repo>/hours.jsonl`, `~/.claude/dispatch/reports/`, `ingest.token`, `ingest-posted.jsonl`, and the repo. Any session can pick it up cold.
