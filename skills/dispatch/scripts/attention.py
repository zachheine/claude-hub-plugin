#!/usr/bin/env python3
"""Estimate the user's attention time on a repo from local Claude Code transcripts.

Every message the user types lands in ~/.claude/projects/<dir>/<session>.jsonl with a
timestamp and the git branch. This script takes the union of short windows around
those messages, across every session on the repo (primary checkout and its worktrees),
and reports minutes per day and per branch.

It measures engagement, not billable hours. Label it that way wherever it is shown.

  attention.py --repo /abs/path/to/checkout [--since YYYY-MM-DD] [--window 5] [--json]
"""
import argparse, glob, json, os, re, sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

def project_dirs(repo: str):
    root = os.path.expanduser('~/.claude/projects')
    key = re.sub(r'[^A-Za-z0-9]', '-', repo.rstrip('/'))  # the app keys project dirs this way
    return [d for d in glob.glob(os.path.join(root, '*')) if os.path.basename(d) == key or os.path.basename(d).startswith(key + '-')]

def typed_by_user(d) -> bool:
    if d.get('type') != 'user' or d.get('isMeta') or d.get('isSidechain'):
        return False
    c = d.get('message', {}).get('content')
    if isinstance(c, str):
        return bool(c.strip()) and not c.lstrip().startswith('<')
    if isinstance(c, list):
        kinds = {x.get('type') for x in c if isinstance(x, dict)}
        if 'tool_result' in kinds:
            return False
        text = ' '.join(x.get('text', '') for x in c if isinstance(x, dict) and x.get('type') == 'text')
        return not text.lstrip().startswith('[Request interrupted')
    return False

def events(repo: str, since: datetime):
    for d in project_dirs(repo):
        for f in glob.glob(os.path.join(d, '*.jsonl')):
            sid = os.path.basename(f)[:-6]
            with open(f, errors='replace') as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if not typed_by_user(rec):
                        continue
                    ts = rec.get('timestamp')
                    if not ts:
                        continue
                    t = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    if t < since:
                        continue
                    yield t, rec.get('gitBranch') or '?', sid

def union_minutes(times, window):
    """Minutes covered by [t-w, t+w] windows, merged."""
    if not times:
        return 0.0
    w = timedelta(minutes=window)
    spans = sorted((t - w, t + w) for t in times)
    total = timedelta(); cur_s, cur_e = spans[0]
    for s, e in spans[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s; cur_s, cur_e = s, e
    total += cur_e - cur_s
    return total.total_seconds() / 60

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', required=True)
    ap.add_argument('--since', default=None, help='YYYY-MM-DD, default 30 days ago')
    ap.add_argument('--window', type=float, default=5.0, help='minutes of attention credited around each message')
    ap.add_argument('--tz', default='America/Los_Angeles')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    since = datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc) if a.since else datetime.now(timezone.utc) - timedelta(days=30)
    try:
        from zoneinfo import ZoneInfo; tz = ZoneInfo(a.tz)
    except Exception:
        tz = timezone.utc
    by_day = defaultdict(list); by_branch = defaultdict(list); by_day_branch = defaultdict(lambda: defaultdict(list))
    n = 0
    for t, br, sid in events(a.repo, since):
        n += 1; day = t.astimezone(tz).date().isoformat()
        by_day[day].append(t); by_branch[br].append(t); by_day_branch[day][br].append(t)
    out = {
        'repo': a.repo, 'since': since.date().isoformat(), 'window_minutes': a.window, 'messages': n,
        'total_minutes': round(sum(union_minutes(v, a.window) for v in by_day.values()), 1),
        'days': {d: {'minutes': round(union_minutes(v, a.window), 1),
                     'branches': {b: round(union_minutes(x, a.window), 1) for b, x in sorted(by_day_branch[d].items())}}
                 for d, v in sorted(by_day.items())},
        'branches': {b: round(union_minutes(v, a.window), 1) for b, v in sorted(by_branch.items(), key=lambda kv: -len(kv[1]))},
        'note': 'attention estimate from typed messages, not billable hours',
    }
    if a.json:
        json.dump(out, sys.stdout, indent=2); print(); return
    print(f"{os.path.basename(a.repo)} since {out['since']}: {n} typed messages, ~{out['total_minutes']/60:.1f} h attention (±{a.window} min windows)")
    print('\nby day:')
    for d, v in out['days'].items():
        top = ', '.join(f"{b} {m:.0f}m" for b, m in sorted(v['branches'].items(), key=lambda kv: -kv[1])[:3])
        print(f"  {d}  {v['minutes']/60:4.1f} h   {top}")
    print('\nby branch:')
    for b, m in list(out['branches'].items())[:15]:
        print(f"  {m/60:5.1f} h  {b}")
    print(f"\n{out['note']}")

if __name__ == '__main__':
    main()
