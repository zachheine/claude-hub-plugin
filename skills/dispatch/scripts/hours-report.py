#!/usr/bin/env python3
"""Daily cross-project hours report, and the one place confirmations are recorded.

  hours-report.py [--date YYYY-MM-DD | --completed] [--day-start HH:MM] [--root ~/Developer/claude] [--window 5]
      Estimate attention time per repo for one WAKING day from local
      Claude Code transcripts, merge any confirmations already in each repo's
      ~/.claude/dispatch/<repo>/hours.jsonl, write the report to
      ~/.claude/dispatch/reports/<date>.md, and print it.

  hours-report.py --confirm --date YYYY-MM-DD repo=hours [repo=hours ...] [--note "..."]
      Record the user's confirmed hours for that day, one line per repo in that
      repo's hours.jsonl. Use "repo=ok" to confirm the estimate as is.

After either of those, the day's rows are POSTed to Superstudio's time-signals ingest
(contract v1, docs/time/DATA-SOURCES.md section 6 in the superstudio repo), plus any
recent day with a report that was never posted or was confirmed since it was. The token
is read from ~/.claude/dispatch/ingest.token (mode 0600); with no token file nothing is
posted and nothing is printed. Titles, branch names and message text are never sent.

  --no-post          never post
  --dry-run          build and validate the payload, print it as JSON, send nothing
                     (no report file, no token needed)
  --post-day DATE    post that waking day only, no report, no catch-up
  --ingest-url URL   --tenant SLUG   override the module defaults

A waking day D runs from D at --day-start (default 04:00) to D+1 at --day-start, so
work at 1 a.m. belongs to the evening it continued from, not to a new date.
--completed picks the most recently finished waking day (yesterday's date when run
after 04:00, the day before when run earlier), which is what the morning report wants.

Attention time is inferred from the timestamps of messages the user typed. It is
an engagement proxy, never billable hours, and every output says so.
"""
import argparse, glob, importlib.util, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('attention', os.path.join(HERE, 'attention.py'))
attention = importlib.util.module_from_spec(spec); spec.loader.exec_module(attention)

DISPATCH = os.path.expanduser('~/.claude/dispatch')
REPORTS = os.path.join(DISPATCH, 'reports')
TOKEN_FILE = os.path.join(DISPATCH, 'ingest.token')
POSTED_LOG = os.path.join(DISPATCH, 'ingest-posted.jsonl')
INGEST_URL = 'https://kgveapiqyduerdilcghk.supabase.co/functions/v1/time-signals-ingest'
TENANT = 'teamprojects'
CATCH_UP_DAYS = 35
RETRY_DELAY = 1.0   # seconds before the one retry

def repos_under(root):
    out = []
    for d in sorted(glob.glob(os.path.join(os.path.expanduser(root), '*'))):
        if os.path.isdir(os.path.join(d, '.git')) or os.path.isfile(os.path.join(d, '.git')):
            out.append(d)
    return out

def tzinfo(tzname):
    try:
        from zoneinfo import ZoneInfo; return ZoneInfo(tzname)
    except Exception:
        return timezone.utc

def parse_hm(hm):
    h, m = hm.split(':'); return int(h), int(m)

def day_bounds(date_str, tzname, day_start='04:00'):
    tz = tzinfo(tzname); h, m = parse_hm(day_start)
    start = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=tz)
    return start, start + timedelta(days=1), tz

def completed_day(tzname, day_start='04:00'):
    """Date label of the most recently finished waking day."""
    tz = tzinfo(tzname); h, m = parse_hm(day_start)
    now = datetime.now(tz)
    today_start = now.replace(hour=h, minute=m, second=0, microsecond=0)
    last = today_start if now >= today_start else today_start - timedelta(days=1)
    return (last - timedelta(days=1)).date().isoformat()

_EVENTS = {}

def load_events(repo, since):
    """Typed-message events for a repo from `since` on; one transcript scan per repo per run."""
    hit = _EVENTS.get(repo)
    if hit is None or hit[0] > since:
        hit = _EVENTS[repo] = (since, list(attention.events(repo, since)))
    return hit[1]

def estimate(repo, start, end, window, scan_since=None):
    times = []; branches = {}; sessions = set()
    for t, br, sid in load_events(repo, min(start, scan_since or start)):
        if t < start or t >= end: continue
        times.append(t); branches.setdefault(br, []).append(t); sessions.add(sid)
    if not times: return None
    return {
        'minutes': round(attention.union_minutes(times, window), 1),
        'messages': len(times),
        'sessions': len(sessions),
        'times': times,
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

def gather(args, date_str, scan_since=None):
    """(repo name, estimate, confirmation) for every repo with typed messages on that waking day."""
    start, end, tz = day_bounds(date_str, args.tz, args.day_start)
    rows = []
    for repo in repos_under(args.root):
        name = os.path.basename(repo)
        est = estimate(repo, start, end, args.window, scan_since)
        if not est: continue
        rows.append((name, est, confirmations(name, date_str)))
    rows.sort(key=lambda r: -r[1]['minutes'])
    return rows

def report(args):
    start, end, tz = day_bounds(args.date, args.tz, args.day_start)
    rows = gather(args, args.date)
    total_est = sum(r[1]['minutes'] for r in rows) / 60
    lines = [f"# Hours report for {args.date}", "",
             f"Waking day: {start.strftime('%a %b %-d %H:%M')} to {end.strftime('%a %b %-d %H:%M')} ({args.tz}). "
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
    post_flow(args, args.date, rows)

def confirm(args):
    start, end, tz = day_bounds(args.date, args.tz, args.day_start)
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
    post_flow(args, args.date)

# ---- Posting to Superstudio (contract v1) ----------------------------------------------

def say(args, msg):
    """User-facing line; stderr under --dry-run so stdout stays pure JSON."""
    print(msg, file=sys.stderr if getattr(args, 'dry_run', False) else sys.stdout)

def redact(text):
    return re.sub(r'ssti_\w*', 'ssti_[redacted]', str(text))

def load_token(args):
    """The token, or None to skip posting. Missing file: silent. Wrong mode: one line, file never read."""
    try:
        mode = os.stat(TOKEN_FILE).st_mode & 0o777
    except OSError:
        return None
    if mode != 0o600:
        say(args, f"Not posting to Superstudio: {TOKEN_FILE} is mode {mode:04o}; run `chmod 600 {TOKEN_FILE}`.")
        return None
    try:
        with open(TOKEN_FILE) as f: token = f.readline().strip()
    except OSError:
        return None
    if not token:
        say(args, f"Not posting to Superstudio: {TOKEN_FILE} is empty.")
        return None
    return token

def repo_slug(repo):
    """owner/repo from the origin remote, or None."""
    try:
        url = subprocess.run(['git', '-C', repo, 'remote', 'get-url', 'origin'], capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return None
    m = re.search(r'github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$', url)
    return f"{m.group(1)}/{m.group(2)}" if m else None

_PRS = {}

def authored_prs(repo):
    """[(number, createdAt, mergedAt)] of the user's PRs on the repo; [] when there is no remote, no gh, or gh fails."""
    if repo in _PRS: return _PRS[repo]
    out = []
    slug = repo_slug(repo)
    if slug:
        try:
            r = subprocess.run(['gh', 'pr', 'list', '--repo', slug, '--author', '@me', '--state', 'all', '--limit', '200',
                                '--json', 'number,createdAt,mergedAt'], capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                for p in json.loads(r.stdout):
                    out.append((p['number'], p.get('createdAt'), p.get('mergedAt')))
        except Exception:
            out = []
    _PRS[repo] = out
    return out

def fetch_prs(repo, start, end):
    """Numbers of PRs created or merged inside [start, end), at most 200."""
    nums = set()
    for n, created, merged in authored_prs(repo):
        for ts in (created, merged):
            if not ts: continue
            try: t = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except ValueError: continue
            if start <= t < end: nums.add(n)
    return sorted(nums)[:200]

def clip_spans(spans, start, end):
    out = []
    for s, e in spans:
        s, e = max(s, start), min(e, end)
        if s < e: out.append((s, e))
    return out

def hours_field(x):
    return max(0.0, min(24.0, round(x, 2)))

def confirmed_field(conf):
    """null when unconfirmed; else 2 decimals, and a positive value that rounds to 0.00 becomes 0.01 (0 means dismissed)."""
    if not conf: return None
    try: v = float(conf['confirmed_h'])
    except (TypeError, ValueError): return None
    c = round(v, 2)
    return 0.01 if (v > 0 and c == 0) else c

def build_payload(date_str, rows, tenant, tz, window, day_start='04:00', prs=None):
    """The v1 body. rows are (name, estimate, confirmation); prs maps repo name to PR numbers."""
    start, end, _ = day_bounds(date_str, tz, day_start)
    tzi = tzinfo(tz); prs = prs or {}
    out = []
    for name, est, conf in rows:
        spans = clip_spans(attention.union_spans(est['times'], window), start, end)
        out.append({
            'key': name,
            'estimate_h': hours_field(est['minutes'] / 60),
            'confirmed_h': confirmed_field(conf),
            'windows': [[s.astimezone(tzi).isoformat(timespec='seconds'), e.astimezone(tzi).isoformat(timespec='seconds')] for s, e in spans],
            'messages': est['messages'],
            'sessions': est['sessions'],
            'prs': list(prs.get(name, []))[:200],
        })
    return {'v': 1, 'day': date_str, 'tenant': tenant, 'rows': out}

def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)

def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

ROW_KEYS = {'key', 'estimate_h', 'confirmed_h', 'windows', 'messages', 'sessions', 'prs'}

def validate_payload(p):
    """Problems under contract v1 section 6 (empty list = fine). The waking day is 04:00 to 04:00, as the server reads it."""
    bad = []
    if not isinstance(p, dict) or set(p) != {'v', 'day', 'tenant', 'rows'}: return ['top-level fields must be exactly v, day, tenant, rows']
    if p['v'] != 1: bad.append('v must be 1')
    try:
        day = datetime.fromisoformat(p['day']); assert re.fullmatch(r'\d{4}-\d\d-\d\d', p['day'])
    except Exception:
        return bad + ['day is not a real YYYY-MM-DD date']
    if not isinstance(p['tenant'], str) or not p['tenant']: bad.append('tenant is empty')
    rows = p['rows']
    if not isinstance(rows, list) or not rows: return bad + ['rows must be a non-empty list']
    if len(rows) > 100: bad.append(f'{len(rows)} rows (max 100)')
    lo, hi = day + timedelta(hours=4), day + timedelta(days=1, hours=4)
    seen = set(); total = 0
    for i, r in enumerate(rows):
        if not isinstance(r, dict) or set(r) != ROW_KEYS:
            bad.append(f'row {i}: fields must be exactly {sorted(ROW_KEYS)}'); continue
        k = r['key']
        if not isinstance(k, str) or not 1 <= len(k) <= 200 or re.search(r'[\x00-\x1f\x7f]', k): bad.append(f'row {i}: bad key')
        elif k in seen: bad.append(f'row {i}: repeated key')
        seen.add(k)
        if not is_num(r['estimate_h']) or not 0 <= r['estimate_h'] <= 24: bad.append(f'row {i}: estimate_h outside 0..24')
        c = r['confirmed_h']
        if c is not None and (not is_num(c) or not (c == 0 or 0.01 <= c <= 24)): bad.append(f'row {i}: confirmed_h must be null, 0, or 0.01..24')
        for f in ('messages', 'sessions'):
            if not is_int(r[f]) or r[f] < 0: bad.append(f'row {i}: {f} must be a whole number from 0')
        if not isinstance(r['prs'], list) or len(r['prs']) > 200 or not all(is_int(n) and n > 0 for n in r['prs']): bad.append(f'row {i}: prs must be at most 200 positive integers')
        w = r['windows']
        if not isinstance(w, list): bad.append(f'row {i}: windows must be a list'); continue
        if len(w) > 500: bad.append(f'row {i}: {len(w)} windows (max 500)')
        total += len(w); prev = None
        for j, pair in enumerate(w):
            try:
                s, e = (datetime.fromisoformat(x) for x in pair)
                assert len(pair) == 2 and s.tzinfo is not None and e.tzinfo is not None
            except Exception:
                bad.append(f'row {i} window {j}: need two ISO times with an offset'); break
            if e <= s: bad.append(f'row {i} window {j}: end is not after start')
            if prev is not None and s < prev: bad.append(f'row {i} window {j}: not sorted or overlapping')
            if s.replace(tzinfo=None) < lo or e.replace(tzinfo=None) > hi: bad.append(f'row {i} window {j}: outside the waking day {p["day"]} 04:00 to 04:00 on its own clock')
            prev = max(prev, e) if prev is not None else e
    if total > 2000: bad.append(f'{total} windows in all (max 2000)')
    if len(json.dumps(p)) > 2_000_000: bad.append('body over 2 MB')
    return bad[:6]   # a handful is enough for one line

def too_many_windows(payload):
    rows = payload['rows']
    return any(len(r['windows']) > 500 for r in rows) or sum(len(r['windows']) for r in rows) > 2000

def prepare_payload(args, date_str, rows):
    """build_payload plus the caps: top 100 rows by estimate, and a wider --window for this post if windows are over the limits."""
    rows = sorted(rows, key=lambda r: -r[1]['minutes'])
    if len(rows) > 100:
        say(args, f"Posting only the top 100 of {len(rows)} repos for {date_str}.")
        rows = rows[:100]
    start, end, _ = day_bounds(date_str, args.tz, args.day_start)
    prs = {name: fetch_prs(os.path.join(os.path.expanduser(args.root), name), start, end) for name, _e, _c in rows}
    w = args.window
    while True:
        payload = build_payload(date_str, rows, args.tenant, args.tz, w, args.day_start, prs)
        if not too_many_windows(payload) or w >= 240: break
        w *= 2
    if w != args.window and not too_many_windows(payload):
        say(args, f"{date_str}: too many windows for one post; merged with a {w:g}-minute window for this post only.")
    return payload

def url_ok(url):
    """https, or plain http to this machine (tests); the bearer token never travels in the clear."""
    u = urllib.parse.urlparse(url)
    return u.scheme == 'https' or (u.scheme == 'http' and u.hostname in ('localhost', '127.0.0.1', '::1'))

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None   # never forward the bearer token to another URL

def post_payload(payload, url, token, timeout=20):
    """(status, body text). status is None after a failed retry. Network errors, timeouts and 5xx get one retry."""
    body = json.dumps(payload, separators=(',', ':')).encode()
    req = urllib.request.Request(url, data=body, method='POST', headers={
        'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'})
    opener = urllib.request.build_opener(_NoRedirect)
    last = (None, 'no response')
    for attempt in (1, 2):
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            last = (e.code, e.read().decode('utf-8', 'replace'))
            if e.code < 500: return last
        except Exception as e:
            last = (None, getattr(e, 'reason', None) or e)
        if attempt == 1: time.sleep(RETRY_DELAY)
    return last[0], redact(last[1])

def log_attempt(day, status, accepted=None, confirmed=None, ignored=None, unmapped=None):
    os.makedirs(os.path.dirname(POSTED_LOG), exist_ok=True)
    rec = {'day': day, 'posted_at': datetime.now(timezone.utc).isoformat(), 'status': status,
           'accepted': accepted, 'confirmed': confirmed, 'ignored': ignored, 'unmapped': unmapped or []}
    with open(POSTED_LOG, 'a') as f: f.write(json.dumps(rec) + '\n')

def reasons(body):
    try:
        d = json.loads(body)
        if isinstance(d, dict):
            r = d.get('reasons') or d.get('error') or d.get('message') or d
            body = '; '.join(map(str, r)) if isinstance(r, list) else r if isinstance(r, str) else json.dumps(r)
    except ValueError:
        pass
    return redact(' '.join(str(body).split())[:400])

def post_day(args, date_str, token, rows=None):
    """Build, validate, send and log one day. Returns the HTTP status, 'error', or None if nothing was sent."""
    if rows is None: rows = gather(args, date_str)
    if not rows: return None
    payload = prepare_payload(args, date_str, rows)
    problems = validate_payload(payload)
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        if problems: say(args, f"{date_str}: payload would not be sent: " + '; '.join(problems))
        return None
    if problems:
        say(args, f"Not posting {date_str} to Superstudio: " + '; '.join(problems))
        return None
    if not url_ok(args.ingest_url):
        say(args, f"Not posting {date_str} to Superstudio: --ingest-url must be https.")
        return None
    status, body = post_payload(payload, args.ingest_url, token)
    if status == 200:
        try:
            d = json.loads(body); a, c, ig, um = d.get('accepted'), d.get('confirmed'), d.get('ignored'), [str(x) for x in d.get('unmapped') or []]
        except (ValueError, AttributeError):
            a = c = ig = None; um = []
        log_attempt(date_str, 200, a, c, ig, um)
        say(args, f"Posted {date_str} to Superstudio: accepted {a}, confirmed {c}, ignored {ig}" + (f", unmapped: {', '.join(um)}" if um else ''))
        return 200
    if status is None:
        log_attempt(date_str, 'error')
        print(f"Posting {date_str} to Superstudio failed: {redact(body)}", file=sys.stderr)
        return 'error'
    log_attempt(date_str, status)
    say(args, f"Superstudio refused {date_str} (HTTP {status}): {reasons(body)}")
    return status

def posted_days():
    """{day: posted_at of its last 200 line}."""
    out = {}
    try: lines = open(POSTED_LOG).read().splitlines()
    except OSError: return out
    for line in lines:
        try:
            rec = json.loads(line)
            if rec.get('status') == 200: out[rec['day']] = datetime.fromisoformat(rec['posted_at'])
        except Exception:
            continue
    return out

def newest_confirmation(day):
    """Latest modification time of any repo's hours.jsonl that holds a confirmation covering the day (the lines carry no timestamp)."""
    newest = None
    for path in glob.glob(os.path.join(DISPATCH, '*', 'hours.jsonl')):
        if confirmations(os.path.basename(os.path.dirname(path)), day):
            t = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
            if newest is None or t > newest: newest = t
    return newest

def catch_up_candidates(today, skip=()):
    """Days from the last 35 with a report file that were never posted, or were confirmed after their last post."""
    posted = posted_days(); cutoff = (datetime.fromisoformat(today) - timedelta(days=CATCH_UP_DAYS)).date().isoformat()
    out = []
    for path in sorted(glob.glob(os.path.join(REPORTS, '*.md'))):
        day = os.path.basename(path)[:-3]
        if not re.fullmatch(r'\d{4}-\d\d-\d\d', day) or not cutoff <= day <= today or day in skip: continue
        conf = newest_confirmation(day)
        if day not in posted or (conf and conf > posted[day]): out.append(day)
    return out

def catch_up(args, token, skip=()):
    today = datetime.now(tzinfo(args.tz)).date().isoformat()
    days = catch_up_candidates(today, skip)
    if not days: return
    scan_since = day_bounds(days[0], args.tz, args.day_start)[0]
    for day in days:
        status = post_day(args, day, token, gather(args, day, scan_since))
        if status in (401, 403, 'error'): break   # a bad token or no network will not get better 35 times over

def post_flow(args, date_str, rows=None, catch_up_too=True):
    """Post one waking day, then catch up. Never raises and never changes the exit code."""
    if args.no_post: return
    try:
        token = None
        if not args.dry_run:
            token = load_token(args)
            if token is None: return
        status = post_day(args, date_str, token, rows)
        if not args.dry_run and catch_up_too and status not in (401, 403, 'error'):
            catch_up(args, token, skip=(date_str,))
    except Exception as e:
        print(f"Posting to Superstudio failed: {redact(e)}", file=sys.stderr)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=None, help='waking-day date label; default: today, or the completed day with --completed')
    ap.add_argument('--completed', action='store_true', help='report the most recently finished waking day')
    ap.add_argument('--day-start', default='04:00', help='when a waking day begins, local time (default 04:00)')
    ap.add_argument('--root', default='~/Developer/claude')
    ap.add_argument('--window', type=float, default=5.0)
    ap.add_argument('--tz', default='America/Los_Angeles')
    ap.add_argument('--confirm', action='store_true')
    ap.add_argument('--note', default=None)
    ap.add_argument('--no-post', action='store_true', help='never post to Superstudio')
    ap.add_argument('--dry-run', action='store_true', help='print the payload as JSON, send nothing, write no report')
    ap.add_argument('--post-day', default=None, metavar='YYYY-MM-DD', help='post that waking day only; no report, no catch-up')
    ap.add_argument('--ingest-url', default=INGEST_URL)
    ap.add_argument('--tenant', default=TENANT)
    ap.add_argument('items', nargs='*')
    a = ap.parse_args()
    if a.date is None:
        a.date = completed_day(a.tz, a.day_start) if a.completed else datetime.now(tzinfo(a.tz)).date().isoformat()
    if a.dry_run and a.confirm: sys.exit('--dry-run does not record confirmations')
    if a.post_day:
        if a.no_post: sys.exit('--post-day and --no-post contradict each other')
        try: datetime.fromisoformat(a.post_day)
        except ValueError: sys.exit('--post-day wants YYYY-MM-DD')
        post_flow(a, a.post_day, catch_up_too=False)
    elif a.dry_run:
        post_flow(a, a.date)
    else:
        confirm(a) if a.confirm else report(a)

if __name__ == '__main__':
    main()
