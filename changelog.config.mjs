export default {
  kinds: [
    { id: 'skill', label: 'Skill' },
    { id: 'release', label: 'Release' },
    { id: 'docs', label: 'Docs' },
    { id: 'chore', label: 'Chore' },
  ],

  classify({ entry, files }) {
    // Evidence first: a file is under skills/
    if (files.some((f) => f.startsWith('skills/'))) {
      return 'skill';
    }

    // A file is under .claude-plugin/
    if (files.some((f) => f.startsWith('.claude-plugin/'))) {
      return 'release';
    }

    // Every file is .md
    if (files.length > 0 && files.every((f) => /\.mdx?$/i.test(f))) {
      return 'docs';
    }

    return 'chore';
  },
};
