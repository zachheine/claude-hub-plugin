#!/usr/bin/env python3
"""Daily cross-project hours report, and the one place confirmations are recorded.

  hours-report.py [--date YYYY-MM-DD] [--root ~/Developer/claude] [--window 5]
      Estimate attention time per repo for one day (default today) from local
      Claude Code transcripts, merge any confirmations already in each repo's
      ~/.claude/dispatch/<repo>/hours.jsonl, write the report to
      ~/.claude/dispatch/reports/<date>.md, and print it.

  hours-report.py --confirm --date YYYY-MM-DD repo=hours [repo=hours ...] [--note "..."]
      Record the user's confirmed hours for that day, one line per repo in that
      repo's hours.jsonl. Use "repo=ok" to confirm the estimate as is.

Attention time is inferred from the timestamps of messages the user typed. It is
an engagement proxy, never billable hours, and every output says so.
"""
import argparse, glob, importlib.util, json, os, sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('attention', os.path.join(HERE, 'attention.py'))
attention = importlib.util.module_from_spec(spec); spec.loader.exec_module(attention)

DISPATCH = os.path.expanduser('~/.claude/dispatch')
REPORTS = os.path.join(DISPATCH, 'reports')

def repos_under(root):
    out = []
    for d in sorted(glob.glob(os.path.join(os.path.expanduser(root), '*'))):
        if os.path.isdir(os.path.join(d, '.git')) or os.path.isfile(os.path.join(d, '.git')):
            out.append(d)
    return out

def day_bounds(date_str, tzname):
    try:
        from zoneinfo import ZoneInfo; tz = ZoneInfo(tzname)
    except Exception:
        tz = timezone.utc
    day = datetime.fromisoformat(date_str).replace(tzinfo=tz)
    return day, day + timedelta(days=1), tz

def estimate(repo, start, end, window):
    times = []; branches = {}
    for t, br, sid in attention.events(repo, start):
        if t >= end: continue
        times.append(t); branches.setdefault(br, []).append(t)
    if not times: return None
    return {
        'minutes': round(attention.union_minutes(times, window), 1),
        'messages': len(times),
        'branches': {b: round(attention.union_minutes(v, window), 1) for b, v in sorted(branches.items(), key=lambda kv: -len(kv[1]))[:3]},
    }

def confirmations(repo_name, date_str):
    path = os.path.join(DISPATCH, repo_name, 'hours.jsonl')
    if not os.path.exists(path): return None
    hit = None
    for line in open(path):
        try: rec = json.loads(line)
        except Exception: continue
        p = rec.get('period')
        if isinstance(p, list) and len(p) == 2 and p[0] <= date_str <= p[1] and rec.get('confirmed_h') is not None:
            hit = rec
    return hit

def report(args):
    start, end, tz = day_bounds(args.date, args.tz)
    rows = []
    for repo in repos_under(args.root):
        name = os.path.basename(repo)
        est = estimate(repo, start, end, args.window)
        if not est: continue
        conf = confirmations(name, args.date)
        rows.append((name, est, conf))
    rows.sort(key=lambda r: -r[1]['minutes'])
    total_est = sum(r[1]['minutes'] for r in rows) / 60
    lines = [f"# Hours report for {args.date}", "",
             "Attention estimates from typed messages in local Claude Code transcripts. Not billable hours.", "",
             "| Repo | Estimate | Confirmed | Messages | Where |", "|---|---|---|---|---|"]
    for name, est, conf in rows:
        where = ', '.join(f"{b} {m:.0f}m" for b, m in est['branches'].items())
        c = f"{conf['confirmed_h']} h" if conf else '—'
        lines.append(f"| {name} | {est['minutes']/60:.1f} h | {c} | {est['messages']} | {where} |")
    lines += ["", f"**Total estimate: {total_est:.1f} h across {len(rows)} repos.**", ""]
    unconfirmed = [r[0] for r in rows if not r[2]]
    if unconfirmed:
        lines.append("Unconfirmed: " + ', '.join(unconfirmed) + ". To record: `hours-report.py --confirm --date "
                     + args.date + " " + ' '.join(f"{n}=ok" for n in unconfirmed) + "` (replace ok with a number to correct).")
    text = '\n'.join(lines) + '\n'
    os.makedirs(REPORTS, exist_ok=True)
    with open(os.path.join(REPORTS, f"{args.date}.md"), 'w') as f: f.write(text)
    print(text)

def confirm(args):
    start, end, tz = day_bounds(args.date, args.tz)
    for item in args.items:
        if '=' not in item: sys.exit(f"bad item {item!r}; use repo=hours or repo=ok")
        name, val = item.split('=', 1)
        repo = os.path.join(os.path.expanduser(args.root), name)
        est = estimate(repo, start, end, args.window)
        est_h = round(est['minutes'] / 60, 2) if est else 0.0
        conf_h = est_h if val.strip().lower() == 'ok' else float(val)
        os.makedirs(os.path.join(DISPATCH, name), exist_ok=True)
        rec = {'period': [args.date, args.date], 'estimate_h': est_h, 'confirmed_h': conf_h, 'note': args.note or ('confirmed as estimated' if val == 'ok' else 'corrected by user')}
        with open(os.path.join(DISPATCH, name, 'hours.jsonl'), 'a') as f: f.write(json.dumps(rec) + '\n')
        print(f"{name}: estimate {est_h} h, confirmed {conf_h} h")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=datetime.now().date().isoformat())
    ap.add_argument('--root', default='~/Developer/claude')
    ap.add_argument('--window', type=float, default=5.0)
    ap.add_argument('--tz', default='America/Los_Angeles')
    ap.add_argument('--confirm', action='store_true')
    ap.add_argument('--note', default=None)
    ap.add_argument('items', nargs='*')
    a = ap.parse_args()
    confirm(a) if a.confirm else report(a)

if __name__ == '__main__':
    main()
