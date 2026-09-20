#!/usr/bin/env node
// changelog.mjs — a changelog derived from git history, not written by hand.
//
// WHAT THIS IS FOR
// ----------------
// A /changelog page that lists what changed, in which no sentence was written
// for it. Every entry is a commit on the default branch's first-parent line:
// its subject, its date, the commits squashed into it, and what its diff
// proves it touched.
//
// A hand-kept changelog is a second copy of a fact, and it rots in a specific,
// nasty way: the entries that stop getting written are the boring ones, so the
// page ends up claiming a quarter of features and no fixes.
//
// WHY git AND NOT THE FORGE API
// -----------------------------
//   1. THE EVIDENCE IS IN THE DIFF, and only git has it. The classifier does
//      not ask what a PR was called; it asks which files moved. An API would
//      need a request per PR to learn less, and would report the PR's head
//      diff rather than what landed.
//   2. NO TOKEN, NO NETWORK, NO RATE LIMIT. This runs on a machine that
//      already has the repo. A forge outage cannot make the page wrong; it
//      cannot even make it late.
//   3. A PRIVATE REPO would need a secret in CI and in every shell, and the
//      failure mode of a missing secret is an empty list — the one thing this
//      page must never render.
//
// `--pr-bodies` is the deliberate exception: it enriches entries with PR prose
// through `gh`, and when `gh` is missing or fails it warns once and leaves
// `body: null`. The list is never shortened by a network failure.
//
// WHY A COMMITTED FILE AND NOT A BUILD-TIME READ
// ----------------------------------------------
// Because the deploy has no history to read. Vercel, Netlify and most CI
// checkouts are shallow. A build-time `git log` works on a laptop and returns
// ten commits in production: a page that is silently, plausibly, 95%
// incomplete. That is worse than a page that is 100% missing, because nobody
// would notice.
//
// So the payload is generated on a machine that has the history, committed to
// the repo, and rendered verbatim.
//
// WHAT THE GATE DOES AND DOES NOT PROMISE
// ---------------------------------------
// `--check` re-derives every entry in the committed payload FROM ITS OWN
// COMMIT and exits 1 if any of them changed. That catches the failure that
// matters: someone edits an entry by hand, or the classifier moves, and the
// page starts describing history that did not happen.
//
// It deliberately does NOT fail merely because newer commits exist. A payload
// derived from history is stale the instant anything merges, so a currency
// gate would red every open PR on every merge — a gate that gets switched off
// in a week. Currency is handled where it can be handled honestly: the payload
// carries its own head commit, and the page says loudly when the running build
// is not in the list.
//
// THE PAYLOAD IS A PURE FUNCTION OF THE HISTORY
// ---------------------------------------------
// No wall clock, no hostname, no environment. Two runs over one checkout
// produce byte-identical JSON, which is what makes the diff gate meaningful.
//
// USAGE
// -----
//   node scripts/changelog.mjs [options]        (run from the repo root)
//
//     --ref <ref>       history to walk (default: origin/<default branch>)
//     --out <path>      payload to write (default: data/changelog.json)
//     --config <path>   classifier config (default: ./changelog.config.mjs)
//     --check           re-derive the existing payload; exit 1 on drift
//     --pr-bodies       fetch PR bodies via `gh`, cached in the payload
//
// Zero dependencies, Node ESM, shells out to `git` only. It runs in any repo
// that has Node and git, with nothing installed.

import { execFile, execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { promisify } from 'node:util';
import { pathToFileURL } from 'node:url';

const execFileAsync = promisify(execFile);

/** The payload format. Bump when a field's meaning changes, not when one is added. */
const PAYLOAD_VERSION = 1;

// ---------------------------------------------------------------------------
// git
// ---------------------------------------------------------------------------

function git(args, cwd) {
  return execFileSync('git', ['-c', 'core.quotePath=false', ...args], {
    cwd,
    encoding: 'utf8',
    maxBuffer: 1 << 28,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

/** Same, but a failure is an answer (null) rather than an exception. */
function gitQuiet(args, cwd) {
  try {
    return git(args, cwd).trim();
  } catch {
    return null;
  }
}

/** The repository root, from wherever this was invoked. */
function repoRoot(cwd) {
  return gitQuiet(['rev-parse', '--show-toplevel'], cwd);
}

/**
 * Which ref the changelog is OF.
 *
 * The default branch on the remote, not HEAD. Run from a feature branch,
 * HEAD's first-parent line includes commits that have not merged and may never
 * merge; a changelog is a record of what landed. `origin/<branch>` is
 * preferred over the local branch because a local branch can be behind, and a
 * payload generated against a stale local main silently omits real entries.
 */
function defaultRef(root) {
  // origin/HEAD is the remote's own answer to "what is the default branch".
  const head = gitQuiet(['symbolic-ref', '--quiet', 'refs/remotes/origin/HEAD'], root);
  const candidates = [];
  if (head) candidates.push(head.replace(/^refs\/remotes\//, ''));
  candidates.push('origin/main', 'origin/master', 'main', 'master');
  for (const ref of candidates) {
    if (gitQuiet(['rev-parse', '--verify', '--quiet', `${ref}^{commit}`], root)) return ref;
  }
  return 'HEAD';
}

/** The origin remote's URL, or null. Recorded so a reader can check the source. */
function remoteUrl(root) {
  return gitQuiet(['remote', 'get-url', 'origin'], root);
}

/**
 * `https://github.com/owner/repo/pull` from the origin remote, or null.
 *
 * Derived rather than written down: a repository that gets renamed or moved
 * would otherwise leave every `#123` pointing at a 404, and the one thing
 * worse than an unlinked PR number is a linked wrong one.
 */
function prBaseUrl(root) {
  const url = remoteUrl(root);
  if (!url) return null;
  const m = /github\.com[:/]([^/]+)\/(.+?)(?:\.git)?$/.exec(url.trim());
  return m ? `https://github.com/${m[1]}/${m[2]}/pull` : null;
}

/** `owner/repo` from the origin remote, for `gh -R`. Null when not GitHub. */
function repoSlug(root) {
  const url = remoteUrl(root);
  if (!url) return null;
  const m = /github\.com[:/]([^/]+)\/(.+?)(?:\.git)?$/.exec(url.trim());
  return m ? `${m[1]}/${m[2]}` : null;
}

// ---------------------------------------------------------------------------
// the walk
// ---------------------------------------------------------------------------

// Record and field separators that cannot occur in a commit message.
const RS = '\x1e';
const US = '\x1f';

/**
 * git's rename shorthand, back to the path that exists now.
 *
 *   `app/{a.ts => b.ts}`  → `app/b.ts`
 *   `a.ts => b.ts`        → `b.ts`
 *
 * The new path is the right one to classify against: a file renamed INTO a
 * watched directory is a file the commit is responsible for.
 */
export function resolveRename(path) {
  const braced = /^(.*)\{(.*) => (.*)\}(.*)$/.exec(path);
  if (braced) return (braced[1] + braced[3] + braced[4]).replace(/\/{2,}/g, '/');
  const plain = / => /.exec(path);
  if (plain) return path.slice(plain.index + 4);
  return path;
}

function parseRecords(out) {
  const commits = [];
  for (const record of out.split(RS)) {
    if (!record.trim()) continue;
    const [sha, date, subject, body, rest = ''] = record.split(US);
    const files = [];
    for (const line of rest.split('\n')) {
      const m = /^(-|\d+)\t(-|\d+)\t(.+)$/.exec(line);
      if (!m) continue;
      files.push({
        path: resolveRename(m[3]),
        // A binary file reports `-` for both. Counting it as zero lines is the
        // truthful reading: it changed, and it has no lines.
        added: m[1] === '-' ? 0 : Number(m[1]),
        removed: m[2] === '-' ? 0 : Number(m[2]),
      });
    }
    commits.push({ sha, date, subject, body, files });
  }
  return commits;
}

/** Every commit on `ref`'s first-parent line, newest first, with its numstat. */
function walk(root, ref) {
  // --diff-merges=first-parent is explicit rather than inherited: git's default
  // for merge commits under --first-parent has changed between versions, and a
  // payload that depends on the git version is not reproducible.
  return parseRecords(
    git(
      [
        'log',
        '--first-parent',
        '--diff-merges=first-parent',
        '--numstat',
        '--no-color',
        `--pretty=format:${RS}%H${US}%cI${US}%s${US}%b${US}`,
        ref,
      ],
      root
    )
  );
}

/** One commit by SHA, in the same shape. Used by --check to re-derive an entry. */
function walkOne(root, sha) {
  const commits = parseRecords(
    git(
      [
        'log',
        '-1',
        '--first-parent',
        '--diff-merges=first-parent',
        '--numstat',
        '--no-color',
        `--pretty=format:${RS}%H${US}%cI${US}%s${US}%b${US}`,
        sha,
      ],
      root
    )
  );
  return commits[0] || null;
}

// ---------------------------------------------------------------------------
// one commit → one entry
// ---------------------------------------------------------------------------

const CONVENTIONAL = /^([a-z]+)(?:\(([^)]+)\))?!?:\s*/;
const TRAILING_PR = /\s*\(#(\d+)\)\s*$/;
/**
 * A squashed PR body is a bulleted list of the commit subjects it swallowed.
 *
 * `* ` only, deliberately. Hyphen bullets are ordinary prose in a hand-written
 * commit body, and git wraps them, so matching `-` harvests half-sentences
 * truncated at the wrap. Measured on a 333-commit repo: widening this to
 * `[*-]` turned 74 empty `steps` lists into mangled ones. A step is a commit
 * subject or it is nothing.
 */
const STEP = /^\* (.+)$/;

/** The directory two segments deep — `app/tests`, `src/lib`, `docs`. */
function area(path) {
  const parts = path.split('/');
  if (parts.length === 1) return '(root)';
  return parts.slice(0, Math.min(2, parts.length - 1)).join('/');
}

/**
 * The default classifier, used when no config supplies one.
 *
 * Evidence first, in the order a reader would apply it: a commit that touches
 * only docs is a docs commit whatever its subject claims. `type` is the
 * understudy, never the replacement — it is what somebody typed, and the file
 * list is what happened.
 */
export const DEFAULT_KINDS = [
  { id: 'feature', label: 'Feature' },
  { id: 'fix', label: 'Fix' },
  { id: 'docs', label: 'Docs' },
  { id: 'tests', label: 'Tests' },
  { id: 'ci', label: 'CI' },
];

const TEST_PATH = /(^|\/)(tests?|__tests__|spec|e2e)\//i;
const TEST_FILE = /\.(test|spec)\.[a-z]+$/i;
const CI_PATH = /^(\.github\/|\.gitlab-ci|\.circleci\/|\.travis\.yml|azure-pipelines|Jenkinsfile|\.buildkite\/)/;

export function defaultClassify({ entry, files }) {
  const every = (fn) => files.length > 0 && files.every(fn);
  if (every((f) => /\.mdx?$/i.test(f))) return 'docs';
  if (every((f) => TEST_PATH.test(f) || TEST_FILE.test(f))) return 'tests';
  if (every((f) => CI_PATH.test(f))) return 'ci';
  if (entry.type === 'fix') return 'fix';
  return 'feature';
}

/**
 * Derive one entry. `classify` sees the entry as derived so far plus the raw
 * file list, and returns a kind id.
 */
export function toEntry(c, classify = defaultClassify) {
  const prMatch = TRAILING_PR.exec(c.subject);
  const subject = prMatch ? c.subject.slice(0, prMatch.index).trim() : c.subject.trim();
  // A merge commit names its PR the other way round.
  const mergePr = /^Merge pull request #(\d+)\b/.exec(subject);
  const pr = prMatch ? Number(prMatch[1]) : mergePr ? Number(mergePr[1]) : null;

  const conv = CONVENTIONAL.exec(subject);

  const steps = [];
  for (const line of (c.body || '').split('\n')) {
    const m = STEP.exec(line.trim());
    // Trailers arrive as their own bullet in some squashes; they are not steps.
    if (m && !/^(co-authored-by|signed-off-by):/i.test(m[1])) steps.push(m[1].trim());
  }

  const areaFiles = new Map();
  let insertions = 0;
  let deletions = 0;
  for (const f of c.files) {
    insertions += f.added;
    deletions += f.removed;
    areaFiles.set(area(f.path), (areaFiles.get(area(f.path)) || 0) + 1);
  }

  const entry = {
    sha: c.sha,
    short: c.sha.slice(0, 8),
    date: c.date,
    subject,
    pr,
    type: conv ? conv[1] : null,
    scope: conv && conv[2] ? conv[2] : null,
    steps,
    files: c.files.length,
    insertions,
    deletions,
    areas: [...areaFiles.entries()]
      .map(([path, files]) => ({ path, files }))
      // files desc, then path — a total order, so the payload is reproducible
      .sort((a, b) => b.files - a.files || a.path.localeCompare(b.path))
      .slice(0, 5),
    kind: null,
    /** PR prose, only with --pr-bodies, and null when `gh` could not answer. */
    body: null,
    /**
     * Reserved. Time is not derivable from a diff, and this generator does not
     * invent it. Per-period figures live in `periods`, from the dispatcher.
     */
    hours: null,
  };

  entry.kind = classify({ entry, files: c.files.map((f) => f.path) });
  return entry;
}

// ---------------------------------------------------------------------------
// config
// ---------------------------------------------------------------------------

/**
 * Load the classifier config, or fall back to the default.
 *
 * A config that exists and throws is fatal: a repo that meant to classify its
 * own way must not silently get the generic reading, because the difference is
 * invisible on the page.
 */
async function loadConfig(root, configPath, explicit) {
  const abs = isAbsolute(configPath) ? configPath : resolve(root, configPath);
  if (!existsSync(abs)) {
    if (explicit) {
      throw new Error(`changelog: --config ${configPath} does not exist.`);
    }
    return { kinds: DEFAULT_KINDS, classify: defaultClassify, path: null };
  }
  const mod = await import(pathToFileURL(abs).href);
  const cfg = mod.default || mod;
  const kinds = Array.isArray(cfg.kinds) && cfg.kinds.length ? cfg.kinds : DEFAULT_KINDS;
  const classify = typeof cfg.classify === 'function' ? cfg.classify : defaultClassify;
  return { kinds, classify, path: abs };
}

// ---------------------------------------------------------------------------
// hours: the dispatcher's periods, copied through
// ---------------------------------------------------------------------------

/**
 * `~/.claude/dispatch/<repo>/hours.jsonl`, one JSON object per line.
 *
 * Copied through verbatim, not summed, not converted. These are the
 * dispatcher's ATTENTION ESTIMATES and the user's own confirmed hours — they
 * are not billable time, and no code here or on the page may present them as
 * such. A malformed line is skipped rather than failing the run; the file is
 * appended to by hand often enough that one bad line must not cost a payload.
 */
function readPeriods(root) {
  const repo = repoName(root);
  if (!repo) return [];
  const path = join(homedir(), '.claude', 'dispatch', repo, 'hours.jsonl');
  if (!existsSync(path)) return [];
  const out = [];
  for (const line of readFileSync(path, 'utf8').split('\n')) {
    const text = line.trim();
    if (!text) continue;
    try {
      out.push(JSON.parse(text));
    } catch {
      // skip: see above
    }
  }
  return out;
}

/** The primary checkout's directory name — the dispatcher's `<repo>` key. */
function repoName(root) {
  const common = gitQuiet(['rev-parse', '--path-format=absolute', '--git-common-dir'], root);
  if (!common) return null;
  return dirname(common).split('/').filter(Boolean).pop() || null;
}

// ---------------------------------------------------------------------------
// PR bodies
// ---------------------------------------------------------------------------

/**
 * Fill `body` for entries that have a PR number, via `gh`.
 *
 * Cached: an entry already in the existing payload with a non-null body is not
 * refetched, so a regeneration after one merge makes one call, not three
 * hundred. Any failure — `gh` missing, not signed in, a deleted PR — warns once
 * and leaves nulls behind. This never fails the run, because a changelog that
 * refuses to write itself when the network is down is a changelog that stops
 * getting regenerated.
 */
async function fillPrBodies(entries, previous, slug) {
  const cached = new Map();
  for (const e of previous?.entries || []) {
    if (e.pr != null && e.body != null) cached.set(e.pr, e.body);
  }

  const wanted = entries.filter((e) => e.pr != null);
  let fetched = 0;
  let warned = false;

  for (const e of wanted) {
    if (cached.has(e.pr)) {
      e.body = cached.get(e.pr);
      continue;
    }
    if (warned) continue; // one failure means gh is unusable; do not retry 300 times
    try {
      const args = ['pr', 'view', String(e.pr), '--json', 'body,title,mergedAt,author'];
      if (slug) args.push('-R', slug);
      const { stdout } = await execFileAsync('gh', args, { maxBuffer: 1 << 26 });
      const data = JSON.parse(stdout);
      const text = typeof data.body === 'string' ? data.body.trim() : '';
      e.body = text || null;
      cached.set(e.pr, e.body);
      fetched += 1;
    } catch (err) {
      warned = true;
      console.warn(
        `changelog: --pr-bodies could not reach \`gh\` (${short(err)}); ` +
          `${wanted.length - fetched} PR bodies left null. The list is complete regardless.`
      );
    }
  }
  return { fetched, cached: wanted.length - fetched, warned };
}

function short(err) {
  const msg = String(err?.message || err).split('\n')[0];
  return msg.length > 120 ? `${msg.slice(0, 117)}…` : msg;
}

// ---------------------------------------------------------------------------
// build
// ---------------------------------------------------------------------------

export function buildChangelog({ root, ref, classify, kinds }) {
  const raw = walk(root, ref);
  if (raw.length === 0) {
    throw new Error(
      `changelog: \`git log --first-parent ${ref}\` returned nothing. A shallow ` +
        'clone cannot produce this payload — fetch the full history and re-run.'
    );
  }
  const entries = raw.map((c) => toEntry(c, classify));

  const byKind = {};
  for (const k of kinds) byKind[k.id] = 0;
  for (const e of entries) byKind[e.kind] = (byKind[e.kind] || 0) + 1;

  return {
    version: PAYLOAD_VERSION,
    ref,
    head: entries[0].sha,
    headShort: entries[0].short,
    headDate: entries[0].date,
    generatedFrom: remoteUrl(root),
    prBase: prBaseUrl(root),
    kinds,
    counts: { total: entries.length, byKind },
    periods: readPeriods(root),
    entries,
  };
}

/** Two spaces and a trailing newline — a diffable file, and the gate's unit. */
export function serialize(payload) {
  return `${JSON.stringify(payload, null, 2)}\n`;
}

function readPayload(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// --check: the gate
// ---------------------------------------------------------------------------

/**
 * Re-derive every entry in the committed payload FROM ITS OWN COMMIT.
 *
 * Fields that are not derived from the commit are excluded from the
 * comparison: `body` comes from the forge and `hours` from a human, and
 * neither is a function of the diff. Everything else must match exactly.
 */
const DERIVED_FIELDS = [
  'sha', 'short', 'date', 'subject', 'pr', 'type', 'scope',
  'steps', 'files', 'insertions', 'deletions', 'areas', 'kind',
];

function plural(n, one, many) {
  return n === 1 ? one : many;
}

function derivedOnly(entry) {
  const out = {};
  for (const k of DERIVED_FIELDS) out[k] = entry[k];
  return JSON.stringify(out);
}

function check({ root, ref, out, classify }) {
  const payload = readPayload(out);
  if (!payload) {
    console.error(`changelog --check: no readable payload at ${out}. Generate one first.`);
    return 1;
  }
  if (gitQuiet(['rev-parse', '--is-shallow-repository'], root) === 'true') {
    console.error(
      'changelog --check: this is a shallow clone, so entries cannot be re-derived. ' +
        'Check out with full history (actions/checkout: fetch-depth: 0).'
    );
    return 1;
  }

  const drift = [];
  const missing = [];
  for (const entry of payload.entries || []) {
    let raw = null;
    try {
      raw = walkOne(root, entry.sha);
    } catch {
      raw = null;
    }
    if (!raw) {
      missing.push(entry);
      continue;
    }
    const rederived = toEntry(raw, classify);
    if (derivedOnly(rederived) !== derivedOnly(entry)) {
      drift.push({ entry, rederived });
    }
  }

  // Information, never a failure: see the header on why currency is not gated.
  const headNow = gitQuiet(['rev-parse', `${ref}^{commit}`], root);
  if (headNow && headNow !== payload.head) {
    const ahead = gitQuiet(['rev-list', '--first-parent', '--count', `${payload.head}..${ref}`], root);
    console.log(
      `changelog --check: ${ref} is ${ahead ?? '?'} commits ahead of the payload ` +
        `(${payload.headShort} → ${headNow.slice(0, 8)}). Not a failure — regenerate when convenient.`
    );
  }

  if (missing.length) {
    console.error(
      `changelog --check: ${missing.length} entries name commits this checkout does not have:`
    );
    for (const e of missing.slice(0, 10)) console.error(`  ${e.short}  ${e.subject}`);
    return 1;
  }

  if (drift.length) {
    console.error(
      `changelog --check: ${drift.length} committed ${plural(drift.length, 'entry', 'entries')} ` +
        'do not match what their own commit derives to. Either an entry was edited by hand, ' +
        'or the classifier moved:'
    );
    for (const d of drift) {
      console.error(`  ${d.entry.short}  ${d.entry.subject}`);
      for (const f of DERIVED_FIELDS) {
        const was = JSON.stringify(d.entry[f]);
        const now = JSON.stringify(d.rederived[f]);
        if (was !== now) console.error(`      ${f}: committed ${was} → derives ${now}`);
      }
    }
    console.error('\nRegenerate with the generator rather than editing the payload.');
    return 1;
  }

  console.log(
    `changelog --check: ${payload.entries.length} ` +
      `${plural(payload.entries.length, 'entry', 'entries')} re-derive identically.`
  );
  return 0;
}

// ---------------------------------------------------------------------------
// cli
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const opts = { ref: null, out: null, config: null, check: false, prBodies: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--check') opts.check = true;
    else if (arg === '--pr-bodies') opts.prBodies = true;
    else if (arg === '--ref') opts.ref = argv[++i];
    else if (arg === '--out') opts.out = argv[++i];
    else if (arg === '--config') opts.config = argv[++i];
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`changelog: unknown argument ${arg}. Try --help.`);
  }
  return opts;
}

const HELP = `changelog.mjs — a changelog derived from git history

  node scripts/changelog.mjs [options]      (run from the repo root)

    --ref <ref>       history to walk        (default: origin/<default branch>)
    --out <path>      payload to write       (default: data/changelog.json)
    --config <path>   classifier config      (default: ./changelog.config.mjs)
    --check           re-derive the committed payload; exit 1 on drift
    --pr-bodies       fetch PR bodies via \`gh\`, cached in the payload
    --help            this text
`;

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(HELP);
    return 0;
  }

  const root = repoRoot(process.cwd());
  if (!root) throw new Error('changelog: not a git repository — no history to derive from.');

  const ref = opts.ref || defaultRef(root);
  const outPath = isAbsolute(opts.out || '')
    ? opts.out
    : resolve(root, opts.out || join('data', 'changelog.json'));
  const { kinds, classify, path: configPath } = await loadConfig(
    root,
    opts.config || 'changelog.config.mjs',
    Boolean(opts.config)
  );

  if (opts.check) return check({ root, ref, out: outPath, classify });

  const previous = readPayload(outPath);
  const payload = buildChangelog({ root, ref, classify, kinds });

  if (opts.prBodies) {
    const res = await fillPrBodies(payload.entries, previous, repoSlug(root));
    console.log(`  pr bodies      ${res.fetched} fetched, ${res.cached} from cache`);
  } else if (previous) {
    // Bodies already paid for stay paid for; a run without --pr-bodies must not
    // silently delete prose the last run fetched.
    const cached = new Map(
      previous.entries.filter((e) => e.body != null).map((e) => [e.sha, e.body])
    );
    for (const e of payload.entries) if (cached.has(e.sha)) e.body = cached.get(e.sha);
  }

  const text = serialize(payload);
  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, text);

  console.log(`wrote ${outPath} (${text.length.toLocaleString('en-US')} bytes)`);
  console.log(`  ref            ${payload.ref}`);
  console.log(`  head           ${payload.headShort}  ${payload.headDate.slice(0, 10)}`);
  console.log(`  config         ${configPath || '(default classifier)'}`);
  console.log(`  entries        ${payload.counts.total}`);
  for (const k of kinds) {
    console.log(`    ${k.id.padEnd(12)} ${payload.counts.byKind[k.id] || 0}`);
  }
  if (payload.periods.length) {
    console.log(`  periods        ${payload.periods.length} (attention estimates, not billable time)`);
  }

  if (previous) {
    if (previous.head === payload.head) {
      console.log('\nthe head is unchanged — nothing has merged since the last run');
    } else {
      const added = payload.counts.total - (previous.counts?.total ?? 0);
      console.log(`\nhead moved ${previous.headShort} → ${payload.headShort} (+${added} entries)`);
    }
    // A changed entry that is NOT new is the interesting case: the classifier
    // moved, and every page that quoted the old reading was wrong.
    const before = new Map(previous.entries.map((e) => [e.sha, derivedOnly(e)]));
    const rewritten = payload.entries.filter(
      (e) => before.has(e.sha) && before.get(e.sha) !== derivedOnly(e)
    );
    if (rewritten.length) {
      console.log(
        `\n${rewritten.length} EXISTING entries were re-derived differently — the ` +
          'classifier changed, not the history:'
      );
      for (const e of rewritten.slice(0, 10)) console.log(`  ${e.short}  ${e.subject}`);
      if (rewritten.length > 10) console.log(`  … and ${rewritten.length - 10} more`);
    }
  }

  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    console.error(String(err?.message || err));
    process.exit(1);
  });
