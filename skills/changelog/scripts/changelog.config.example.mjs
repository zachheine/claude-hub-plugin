// changelog.config.mjs — what the kinds mean in THIS repo.
//
// Copy to the repo root as `changelog.config.mjs`. The generator picks it up
// automatically; `--config <path>` points somewhere else.
//
// WITHOUT A CONFIG the generator uses a generic classifier: docs (only .md
// files), tests (only test paths), ci (only CI config), fix (conventional type
// `fix`), feature (everything else). That is a fine starting point and a poor
// finish, because it classifies by what somebody TYPED in the subject line.
//
// THE POINT OF A CONFIG IS EVIDENCE. A repo that can name a file whose change
// proves something can classify on that file instead of on prose. mrmt-platform
// keys on its committed SVG snapshots: a commit that moved
// `app/tests/engines/__snapshots__/H11057.ply.svg` changed a drawing, and that
// is not an inference — the drawing is committed and it is different. A subject
// line saying `feat(plywood):` is a claim; a moved snapshot is a fact.
//
// Find your repo's equivalent: committed snapshots, golden files, generated
// schemas, migration directories, a lockfile. Anything whose presence in a
// diff means something specific and cannot be faked by a commit message.

export default {
  /**
   * The kinds, in the order the page should show their toggles.
   *
   * `id` goes in the payload and in the page's `?kind=off` query params, so it
   * is a stable identifier: renaming one rewrites every entry and reds
   * `--check` until the payload is regenerated. `label` is what a reader sees
   * and can change freely.
   *
   * Keep the list short. Five kinds a reader can hold in their head beat
   * fifteen that turn the filter row into a second navigation problem.
   */
  kinds: [
    { id: 'drawings', label: 'Drawings' },
    { id: 'schema', label: 'Schema' },
    { id: 'feature', label: 'Feature' },
    { id: 'fix', label: 'Fix' },
    { id: 'docs', label: 'Docs' },
    { id: 'chore', label: 'Chore' },
  ],

  /**
   * One commit → one kind id.
   *
   * @param {object} arg
   * @param {object} arg.entry  the entry as derived so far: subject, pr, type,
   *                            scope, steps, files, insertions, deletions,
   *                            areas. `kind` is not set yet — that is your job.
   * @param {string[]} arg.files  every path the commit touched, renames already
   *                              resolved to the path that exists now.
   * @returns {string} one of the `id`s above.
   *
   * RULES THIS FUNCTION MUST FOLLOW, because `--check` re-derives every
   * committed entry through it:
   *
   *   - PURE. No clock, no network, no filesystem, no environment. Two runs
   *     over one checkout must produce the same answer, or the gate is noise.
   *   - TOTAL. Return a kind for every commit, including the empty one. An
   *     undefined kind lands in the payload as `null` and the page renders a
   *     chip with no name.
   *   - STABLE. Every edit here rewrites history's reading. The generator
   *     prints which existing entries changed; read that list before
   *     committing the payload, because it is the set of entries whose old
   *     description was wrong or whose new one is.
   */
  classify({ entry, files }) {
    // Evidence first: a committed drawing moved. Not a claim about intent.
    if (files.some((f) => f.startsWith('app/tests/engines/__snapshots__/'))) {
      return 'drawings';
    }

    // A migration is a migration whatever the subject says, and it is the one
    // kind a reader scans for when something broke at a particular date.
    if (files.some((f) => /^(db|supabase)\/migrations\//.test(f))) {
      return 'schema';
    }

    // Only then fall back to what somebody typed. Conventional-commit `type`
    // is the understudy, never the replacement.
    if (entry.type === 'fix') return 'fix';
    // `files.length > 0 &&` is not defensive noise: an empty commit satisfies
    // `every()` vacuously, so without the guard a commit that touched no files
    // at all lands under the docs kind.
    if (entry.type === 'docs' || (files.length > 0 && files.every((f) => /\.mdx?$/i.test(f)))) {
      return 'docs';
    }
    if (entry.type === 'chore' || entry.type === 'test' || entry.type === 'ci') return 'chore';

    return 'feature';
  },
};
