---
name: changelog
description: Build or maintain a changelog that is DERIVED from git history rather than written by hand — a zero-dependency generator, a committed JSON payload, a CI gate, and a /changelog page. Use when the user asks for a changelog, release notes, a "what shipped" page, or a history of changes; when a hand-kept CHANGELOG.md has gone stale; when a dispatcher is told to regenerate the changelog after a merge train; or when anyone proposes writing changelog entries by hand.
---

# Changelog Charter

A changelog nobody writes is a changelog nobody forgets to write. Every entry on the page is a commit on the default branch's first-parent line, and no sentence on it was composed for it.

You have two jobs: **scaffold** the pattern into a repo that lacks it, and **regenerate** after merges. Do the second in one command; do the first once, carefully.

## The rules the generator enforces, and why

State these when you scaffold. They are the design, not preferences, and a repo that breaks one gets the failure named beside it.

1. **Derived, not written.** An entry is a function of its commit. A hand-kept changelog is a second copy of a fact, and it rots in a specific direction: the entries that stop getting written are the boring ones, so the page ends up claiming a quarter of features and no fixes.
2. **git, not the forge API.** The evidence is in the diff and only git has it — the classifier asks which files moved, not what a PR was called. No token, no network, no rate limit; a forge outage cannot make the page wrong. `--pr-bodies` is the one exception, and when `gh` fails it warns once and leaves `body: null` rather than shortening the list.
3. **A committed payload, not a build-time read.** Vercel, Netlify and `actions/checkout` all check out shallow by default. A build-time `git log` returns everything on a laptop and ten commits in production: a page that is silently, plausibly 95% incomplete, which is worse than one that is 100% missing because nobody notices. Generate where the history is, commit the JSON, render it verbatim.
4. **Deterministic.** No wall clock, no hostname, no environment. Two runs over one checkout produce byte-identical JSON. This is what makes the gate meaningful; without it `--check` is noise.
5. **The gate holds entries true, not current.** `--check` re-derives every committed entry from its own commit and fails on drift. It deliberately does **not** fail because newer commits exist: a history-derived file is stale the instant anything merges, so a currency gate reds every open PR on every merge and gets switched off within a week. Currency is reported instead — the payload carries its head, and the page says loudly when the running build is not in the list.
6. **Evidence beats the subject line.** Conventional-commit `type` is the understudy, never the replacement. A repo that can name a file whose change proves something should classify on that file.

## Job A: scaffold the pattern into a repo

Do these in order. Commit as you go.

### 1. Copy the generator

```bash
mkdir -p scripts
cp <this skill>/scripts/changelog.mjs scripts/changelog.mjs
```

One file, zero dependencies, Node ESM, shells out to `git` only. It needs no `package.json` entry to work; add one if the repo has an npm script convention:

```json
"scripts": { "changelog": "node scripts/changelog.mjs" }
```

### 2. Write the config

Copy `scripts/changelog.config.example.mjs` to the repo root as `changelog.config.mjs` and replace its rules with this repo's. Without a config the generator uses a generic classifier (docs / tests / ci / fix / feature) that reads subject lines — fine to start, poor to finish.

Find this repo's evidence before writing the `classify` function. Ask what file, if it appears in a diff, proves something a commit message could only claim: committed snapshots or golden files, a migrations directory, a generated schema, a lockfile, a public API surface. Key on that first and fall back to `entry.type` after.

`classify` must be **pure** (no clock, network or filesystem), **total** (return a kind for every commit, including one that touched no files — `[].every()` is vacuously true, which is a real bug in naive rules), and **stable** (a `kinds` id is written into every entry and into the page's query params, so renaming one rewrites history's reading and reds `--check` until the payload is regenerated).

Keep the list to about five kinds. Fifteen turns the filter row into a second navigation problem.

### 3. Generate the first payload

```bash
node scripts/changelog.mjs
```

Defaults: ref `origin/<default branch from origin/HEAD>`, out `data/changelog.json`, config `./changelog.config.mjs` if present. Run from the repo root. Flags:

```
--ref <ref>       history to walk
--out <path>      payload to write
--config <path>   classifier config
--check           re-derive the committed payload; exit 1 on drift
--pr-bodies       fetch PR bodies via `gh`, cached in the payload
```

Read the per-kind counts it prints before committing. A classifier that puts 95% of commits in one kind has not classified anything, and the page's filters will have nothing to do.

**Commit the payload.** It is generated output that is deliberately tracked; say so in the commit message so the next person does not gitignore it.

### 4. Add the CI gate

One step, and it needs full history:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0          # --check re-derives from each entry's own commit
- run: node scripts/changelog.mjs --check
```

Without `fetch-depth: 0` the gate cannot read the commits it is checking and says so rather than passing vacuously. Do not add a step that regenerates the payload in CI — that is the build-time read rule 3 forbids, wearing a different hat.

### 5. Build the page

Render the committed JSON in the repo's own stack. Read it **server-side**: the payload is hundreds of kilobytes and must not enter a client bundle.

- **Next.js** — `import payload from '@/data/changelog.json'` in a server component at `app/changelog/page.tsx`. Group by month, print the fields, pass only what is interactive to a client component.
- **Astro** — the same import in the frontmatter of `src/pages/changelog.astro`; it never reaches the client.
- **No app, or a static site** — copy `templates/changelog.html` next to the payload and serve the directory. Vanilla JS, inline CSS, light and dark via `prefers-color-scheme`, no framework and no CDN. It fetches `./changelog.json` relative to itself.

Whatever the stack, the page **computes nothing about history**. It groups, counts and prints. Keep the entries in the payload's order — it is git's topological order along the first-parent line, and re-sorting by date reorders commits whose committer dates disagree with the topology.

Render the standing banner. Set a build-commit global from whatever the platform stamps (`VERCEL_GIT_COMMIT_SHA`, `COMMIT_REF`, `GITHUB_SHA`) and compare it to the entries: in the list means complete as of this build; not in the list means something merged after the payload and the page says so. With no stamp the page says it cannot tell. **Never let "unknown" render as "current"** — that is the one lie the whole page exists to prevent.

### 6. Tell the dispatcher

Add one line to CLAUDE.md, under whatever heading holds repo commands:

```
Changelog: `node scripts/changelog.mjs`
```

The `dispatch` skill looks for exactly this — a `npm run changelog`, a `scripts/*changelog*`, or a note in CLAUDE.md — when it keeps the books after a merge train. Without the line it reports that the repo has no generator and moves on, and the page quietly falls behind.

## Job B: regenerate after merges

```bash
git pull --ff-only origin main
node scripts/changelog.mjs
git add data/changelog.json
git commit -m "chore(changelog): regenerate after <short shas>"
```

Read the generator's closing report before committing. `head moved X → Y (+n entries)` is routine. **`n EXISTING entries were re-derived differently` is not**: it means the classifier moved, not the history, and the listed entries are ones whose old description was wrong or whose new one is. Look at them.

Use `--pr-bodies` when the page shows PR prose. Bodies are cached — an entry already in the payload with a non-null body is not refetched — so a regeneration after one merge makes one `gh` call, not three hundred.

When `--check` fails, do not edit the payload. Regenerate it, and if the diff is larger than the merge explains, the classifier changed and that is the thing to review.

## Hours: what `periods` is, and what it is not

The payload carries a `periods` array, copied verbatim from `~/.claude/dispatch/<repo>/hours.jsonl` when that file exists. Each line is one bookkeeping period the `dispatch` skill wrote: an `estimate_h` and a `confirmed_h`.

- `estimate_h` is **attention time**, inferred from typed messages in local session transcripts by `skills/dispatch/scripts/attention.py`. It is a proxy measured from keystrokes, not a record of work.
- `confirmed_h` is what the user said when the dispatcher asked them to confirm or correct the estimate. It is their answer to a question, recorded once.

**Neither is billable time, and neither was ever recorded as such.** Label them on the page in those words. A column of hours beside a changelog will be read as an invoice by the next person who opens it, and the estimate cannot support that reading. The generator does not compute hours, does not sum periods, and leaves each entry's `hours` field `null` — time is not derivable from a diff, and the generator does not invent what it cannot derive.

If the repo has no `hours.jsonl`, `periods` is `[]` and the page shows nothing. That is the normal case.

## Payload shape

```jsonc
{
  "version": 1,
  "ref": "origin/main",
  "head": "<40 hex>", "headShort": "<8 hex>", "headDate": "<ISO with offset>",
  "generatedFrom": "<origin remote url or null>",
  "prBase": "https://github.com/owner/repo/pull",   // or null — see below
  "kinds": [{ "id": "feature", "label": "Feature" }],
  "counts": { "total": 332, "byKind": { "feature": 266 } },
  "periods": [],
  "entries": [{
    "sha": "", "short": "", "date": "", "subject": "",   // trailing (#N) lifted into pr
    "pr": 147,                                            // or null
    "type": "feat", "scope": "pdf",                       // conventional parse, or null
    "steps": ["…"],                                       // subjects squashed into this commit
    "files": 70, "insertions": 9310, "deletions": 1015,
    "areas": [{ "path": "app/tests", "files": 45 }],      // top-level dirs, most files first
    "kind": "feature",
    "body": null,                                         // PR prose, only with --pr-bodies
    "hours": null                                         // reserved; see above
  }]
}
```

`prBase` is derived from the origin remote rather than written down: a repository that gets renamed leaves every `#123` pointing at a 404, and the one thing worse than an unlinked PR number is a linked wrong one. When there is no recognisable GitHub remote it is `null` and the page must render the number as text, not as a link to a repository that may not be this one.

## Measured facts

Carry these; they are cheaper to read than to rediscover.

- **`steps` matches `* ` bullets only.** A squashed PR body is a bulleted list of the subjects it swallowed, and GitHub writes them with an asterisk. Hyphen bullets are ordinary prose in a hand-written commit body, and git wraps them — measured on a 333-commit repository, widening the pattern to `[*-]` turned 74 empty `steps` lists into mangled half-sentences truncated at the wrap.
- **`--diff-merges=first-parent` is passed explicitly.** git's default for merge commits under `--first-parent` has changed between versions, and a payload that depends on the git version is not reproducible.
- **A payload's head can leave the first-parent line.** In a repo whose merges are "Merge origin/main into feat/x" commits — feature branch as first parent, main as second — the previous tip of main becomes a second parent and falls off the line. A payload generated before such a merge then names commits that `git log --first-parent origin/main` no longer reports. Nothing is lost and nothing is wrong; regenerating produces the current line. Do not treat it as a parser fault, and do not expect an old payload's entry set to be a subset of a newer one.
- **Renames are resolved to the path that exists now.** A file renamed *into* a watched directory is a file the commit is responsible for.
- **A binary file's numstat is `-`/`-`** and counts as zero lines: it changed, and it has no lines.
