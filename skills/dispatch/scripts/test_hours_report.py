"""Tests for the Superstudio posting step in hours-report.py.

  python3 -m unittest skills/dispatch/scripts/test_hours_report.py

The endpoint is an in-process http.server on a free port. Nothing touches the real
~/.claude/dispatch: every path the script reads or writes is pointed at a temp dir.
"""
import contextlib, importlib.util, io, json, os, sys, tempfile, threading, unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))

def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

attention = load('attention', 'attention.py')
hr = load('hours_report', 'hours-report.py')

UTC = timezone.utc
TZ = 'America/Los_Angeles'
DAY = '2026-10-28'   # PDT, UTC-7
TOKEN = 'ssti_' + 'ab12' * 16

# The key sets of superstudio's docs/time/samples/claude-day.sample.json (contract v1).
SAMPLE_TOP = {'v', 'day', 'tenant', 'rows'}
SAMPLE_ROW = {'key', 'estimate_h', 'confirmed_h', 'windows', 'messages', 'sessions', 'prs'}

def local(h, m=0, day=28):
    """A UTC datetime for a Pacific wall-clock time on 2026-10-<day> (PDT)."""
    return datetime(2026, 10, day, h, m, tzinfo=timezone(timedelta(hours=-7))).astimezone(UTC)

def est(times, messages=None, sessions=1, minutes=None):
    return {'minutes': minutes if minutes is not None else 60.0, 'messages': messages or len(times),
            'sessions': sessions, 'times': times, 'branches': {}}

class Fake:
    """A fake ingest endpoint. `responses` is a list of (status, body|None); None drops the connection. The last repeats."""
    def __init__(self, responses):
        self.responses = list(responses); self.requests = []
        fake = self
        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                fake.requests.append({'headers': dict(self.headers), 'body': json.loads(body), 'path': self.path})
                status, out = fake.responses[min(len(fake.requests), len(fake.responses)) - 1]
                if out is None:
                    self.close_connection = True; self.connection.close(); return
                data = json.dumps(out).encode()
                self.send_response(status); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
            def log_message(self, *a): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/functions/v1/time-signals-ingest'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
    def close(self):
        self.server.shutdown(); self.server.server_close()

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.saved = {k: getattr(hr, k) for k in ('DISPATCH', 'REPORTS', 'TOKEN_FILE', 'POSTED_LOG', 'RETRY_DELAY')}
        hr.DISPATCH = d; hr.REPORTS = os.path.join(d, 'reports')
        hr.TOKEN_FILE = os.path.join(d, 'ingest.token'); hr.POSTED_LOG = os.path.join(d, 'ingest-posted.jsonl')
        hr.RETRY_DELAY = 0
        os.makedirs(hr.REPORTS)
        hr._PRS.clear(); hr._EVENTS.clear()
        hr._PRS[os.path.join(d, 'repo-a')] = []   # no gh calls in tests
        self.addCleanup(lambda: [setattr(hr, k, v) for k, v in self.saved.items()])
        self.fakes = []
    def serve(self, *responses):
        f = Fake(responses); self.fakes.append(f); self.addCleanup(f.close); return f
    def args(self, url='http://127.0.0.1:9/x', **kw):
        a = dict(no_post=False, dry_run=False, ingest_url=url, tenant='teamprojects', tz=TZ, day_start='04:00',
                 window=5.0, root=self.tmp.name)
        a.update(kw); return SimpleNamespace(**a)
    def write_token(self, mode=0o600):
        with open(hr.TOKEN_FILE, 'w') as f: f.write(TOKEN + '\n')
        os.chmod(hr.TOKEN_FILE, mode)
    def rows(self):
        return [('repo-a', est([local(9, 0), local(9, 30)], sessions=2), None)]
    def run_flow(self, args, rows=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            hr.post_flow(args, DAY, self.rows() if rows is None else rows, catch_up_too=False)
        return out.getvalue(), err.getvalue()
    def log_lines(self):
        try: return [json.loads(l) for l in open(hr.POSTED_LOG)]
        except OSError: return []

class AttentionSpans(unittest.TestCase):
    T = [datetime(2026, 10, 28, 17, m, tzinfo=UTC) for m in (0, 4, 30, 41, 42)]

    def test_union_minutes_unchanged(self):
        # w=5: 17:00 and 17:04 merge (16:55-17:09); 17:30 alone (17:25-17:35); 17:41 and 17:42 merge (17:36-17:47)
        self.assertEqual(attention.union_minutes(self.T, 5), 14 + 10 + 11)
        self.assertEqual(attention.union_minutes(self.T, 1), 2 + 2 + 2 + 3)
        self.assertEqual(attention.union_minutes([], 5), 0.0)

    def test_union_spans_sorted_non_overlapping_and_same_total(self):
        spans = attention.union_spans(list(reversed(self.T)), 5)
        self.assertEqual(len(spans), 3)
        for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
            self.assertLess(e1, s2)
        self.assertEqual(sum((e - s for s, e in spans), timedelta()).total_seconds() / 60, 35)

    def test_touching_spans_merge(self):
        t = [datetime(2026, 10, 28, 17, 0, tzinfo=UTC), datetime(2026, 10, 28, 17, 10, tzinfo=UTC)]
        self.assertEqual(len(attention.union_spans(t, 5)), 1)

class Payload(Base):
    def test_shape_equals_sample_key_set(self):
        p = hr.build_payload(DAY, self.rows(), 'teamprojects', TZ, 5.0, prs={'repo-a': [3, 1]})
        self.assertEqual(set(p), SAMPLE_TOP)
        self.assertEqual(set(p['rows'][0]), SAMPLE_ROW)
        r = p['rows'][0]
        self.assertEqual((p['v'], p['day'], p['tenant'], r['key'], r['sessions'], r['messages'], r['prs']),
                         (1, DAY, 'teamprojects', 'repo-a', 2, 2, [3, 1]))
        self.assertEqual(r['windows'], [['2026-10-28T08:55:00-07:00', '2026-10-28T09:05:00-07:00'],
                                        ['2026-10-28T09:25:00-07:00', '2026-10-28T09:35:00-07:00']])
        self.assertEqual(hr.validate_payload(p), [])

    def test_clipped_at_04_00_both_ends_not_dropped(self):
        rows = [('repo-a', est([local(4, 2), local(3, 58, day=29)]), None)]
        w = hr.build_payload(DAY, rows, 't', TZ, 5.0)['rows'][0]['windows']
        self.assertEqual(w, [['2026-10-28T04:00:00-07:00', '2026-10-28T04:07:00-07:00'],
                             ['2026-10-29T03:53:00-07:00', '2026-10-29T04:00:00-07:00']])

    def test_span_wholly_outside_is_dropped(self):
        rows = [('repo-a', est([local(3, 30), local(9)]), None)]
        w = hr.build_payload(DAY, rows, 't', TZ, 5.0)['rows'][0]['windows']
        self.assertEqual(len(w), 1)

    def test_windows_sorted_and_non_overlapping(self):
        times = [local(9, 0), local(9, 30), local(9, 3), local(13, 0), local(1, 0, day=29)]
        w = hr.build_payload(DAY, [('repo-a', est(times), None)], 't', TZ, 5.0)['rows'][0]['windows']
        parsed = [[datetime.fromisoformat(x) for x in pair] for pair in w]
        self.assertEqual(len(parsed), 4)
        for (s1, e1), (s2, e2) in zip(parsed, parsed[1:]):
            self.assertLessEqual(e1, s2)
        self.assertEqual(hr.validate_payload(hr.build_payload(DAY, [('repo-a', est(times), None)], 't', TZ, 5.0)), [])

    def test_confirmed_rounding(self):
        c = hr.confirmed_field
        self.assertIsNone(c(None))
        self.assertEqual(c({'confirmed_h': 0}), 0)
        self.assertEqual(c({'confirmed_h': 0.004}), 0.01)
        self.assertEqual(c({'confirmed_h': 1.5}), 1.5)
        self.assertEqual(c({'confirmed_h': 1.4567}), 1.46)

    def test_validation_catches_contract_violations(self):
        good = hr.build_payload(DAY, self.rows(), 't', TZ, 5.0)
        def bad(mut):
            p = json.loads(json.dumps(good)); mut(p); return hr.validate_payload(p)
        self.assertTrue(bad(lambda p: p['rows'][0].update(title='x')))
        self.assertTrue(bad(lambda p: p['rows'][0].update(messages=-1)))
        self.assertTrue(bad(lambda p: p['rows'][0].update(prs=[0])))
        self.assertTrue(bad(lambda p: p['rows'][0].update(confirmed_h=0.004)))
        self.assertTrue(bad(lambda p: p['rows'][0].update(windows=[['2026-10-28T03:00:00-07:00', '2026-10-28T03:30:00-07:00']])))
        self.assertTrue(bad(lambda p: p['rows'][0].update(windows=[['2026-10-28T10:00:00', '2026-10-28T10:30:00']])))
        self.assertTrue(bad(lambda p: p['rows'][0].update(windows=[['2026-10-28T10:00:00-07:00', '2026-10-28T10:30:00-07:00'],
                                                                   ['2026-10-28T10:20:00-07:00', '2026-10-28T10:40:00-07:00']])))
        self.assertTrue(bad(lambda p: p['rows'].append(dict(p['rows'][0]))))   # repeated key
        self.assertTrue(bad(lambda p: p['rows'].__setitem__(slice(None), [dict(p['rows'][0], key=f'k{i}') for i in range(101)])))

    def test_too_many_windows_widens_the_window_for_that_post(self):
        times = [local(5) + timedelta(minutes=12 * i) for i in range(60)]   # 60 windows at 5 min; one at >=7 min
        a = self.args(root=self.tmp.name)
        orig = hr.too_many_windows
        hr.too_many_windows = lambda p: len(p['rows'][0]['windows']) > 20
        self.addCleanup(lambda: setattr(hr, 'too_many_windows', orig))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            p = hr.prepare_payload(a, DAY, [('repo-a', est(times), None)])
        self.assertLessEqual(len(p['rows'][0]['windows']), 20)
        self.assertIn('merged with a', out.getvalue())

class Posting(Base):
    def test_missing_token_file_makes_no_request_and_prints_nothing(self):
        f = self.serve((200, {}))
        out, err = self.run_flow(self.args(f.url))
        self.assertEqual((f.requests, out, err), ([], '', ''))
        self.assertEqual(self.log_lines(), [])

    def test_loose_mode_token_is_not_read_and_says_chmod(self):
        self.write_token(0o644)
        f = self.serve((200, {}))
        reads = []
        real_open = open
        def spy(path, *a, **k):
            if str(path) == hr.TOKEN_FILE: reads.append(path)
            return real_open(path, *a, **k)
        hr.open = spy; self.addCleanup(lambda: delattr(hr, 'open'))
        out, err = self.run_flow(self.args(f.url))
        self.assertEqual(f.requests, [])
        self.assertEqual(reads, [])
        self.assertIn('chmod 600', out)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertNotIn(TOKEN, out + err)

    def test_200_posts_once_logs_once_and_prints_one_line(self):
        self.write_token()
        f = self.serve((200, {'accepted': 1, 'confirmed': 0, 'unmapped': ['repo-a'], 'ignored': 0}))
        out, err = self.run_flow(self.args(f.url))
        self.assertEqual(len(f.requests), 1)
        req = f.requests[0]
        self.assertEqual(req['headers']['Authorization'], 'Bearer ' + TOKEN)
        self.assertEqual(req['headers']['Content-Type'], 'application/json')
        self.assertEqual(set(req['body']), SAMPLE_TOP)
        self.assertEqual(out.strip(), f'Posted {DAY} to Superstudio: accepted 1, confirmed 0, ignored 0, unmapped: repo-a')
        (line,) = self.log_lines()
        self.assertEqual((line['day'], line['status'], line['accepted'], line['confirmed'], line['ignored'], line['unmapped']),
                         (DAY, 200, 1, 0, 0, ['repo-a']))
        self.assertEqual(set(line), {'day', 'posted_at', 'status', 'accepted', 'confirmed', 'ignored', 'unmapped'})
        self.assertNotIn(TOKEN, open(hr.POSTED_LOG).read() + out + err)

    def test_network_error_retries_exactly_once(self):
        self.write_token()
        f = self.serve((200, None))   # drops the connection every time
        out, err = self.run_flow(self.args(f.url))
        self.assertEqual(len(f.requests), 2)
        self.assertEqual([l['status'] for l in self.log_lines()], ['error'])
        self.assertIn('failed', err)
        self.assertNotIn(TOKEN, out + err)

    def test_network_error_then_success(self):
        self.write_token()
        f = self.serve((200, None), (200, {'accepted': 1, 'confirmed': 0, 'unmapped': [], 'ignored': 0}))
        out, _ = self.run_flow(self.args(f.url))
        self.assertEqual(len(f.requests), 2)
        self.assertIn('Posted', out)

    def test_422_is_not_retried_and_prints_reasons(self):
        self.write_token()
        f = self.serve((422, {'reasons': ['rows[0].windows[0] outside day', f'token {TOKEN} echoed']}))
        out, err = self.run_flow(self.args(f.url))
        self.assertEqual(len(f.requests), 1)
        self.assertIn('422', out); self.assertIn('outside day', out)
        self.assertNotIn(TOKEN, out + err)
        self.assertEqual([l['status'] for l in self.log_lines()], [422])

    def test_401_and_403_are_not_retried(self):
        self.write_token()
        for code in (401, 403):
            f = self.serve((code, {'error': 'no'}))
            self.run_flow(self.args(f.url))
            self.assertEqual(len(f.requests), 1)

    def test_redirect_is_not_followed(self):
        self.write_token()
        target = self.serve((200, {}))
        class R(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(307); self.send_header('Location', target.url); self.send_header('Content-Length', '0'); self.end_headers()
            def log_message(self, *a): pass
        from http.server import ThreadingHTTPServer as S
        srv = S(('127.0.0.1', 0), R); threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        self.run_flow(self.args(f'http://127.0.0.1:{srv.server_address[1]}/x'))
        self.assertEqual(target.requests, [])

    def test_invalid_payload_is_not_sent(self):
        self.write_token()
        f = self.serve((200, {}))
        rows = [('repo-a', est([local(4, 30, day=29)]), None)]
        out, _ = self.run_flow(self.args(f.url, day_start='05:00'), rows)   # clipped at 05:00, but the server reads 04:00
        self.assertEqual(f.requests, [])
        self.assertIn('Not posting', out)
        self.assertEqual(len(out.strip().splitlines()), 1)

    def test_no_post_and_dry_run(self):
        self.write_token()
        f = self.serve((200, {}))
        self.assertEqual(self.run_flow(self.args(f.url, no_post=True)), ('', ''))
        self.assertEqual(f.requests, [])
        os.remove(hr.TOKEN_FILE)   # dry-run needs no token
        out, err = self.run_flow(self.args(f.url, dry_run=True))
        self.assertEqual(f.requests, [])
        self.assertEqual(set(json.loads(out)), SAMPLE_TOP)
        self.assertEqual(self.log_lines(), [])

    def test_plain_http_to_a_remote_host_is_refused(self):
        self.write_token()
        out, _ = self.run_flow(self.args('http://example.com/x'))
        self.assertIn('must be https', out)
        self.assertTrue(hr.url_ok(hr.INGEST_URL))
        self.assertEqual(hr.TENANT, 'teamprojects')

class CatchUp(Base):
    def report_file(self, day):
        open(os.path.join(hr.REPORTS, f'{day}.md'), 'w').write('x')
    def posted(self, day, at):
        with open(hr.POSTED_LOG, 'a') as f:
            f.write(json.dumps({'day': day, 'posted_at': at.isoformat(), 'status': 200, 'accepted': 1, 'confirmed': 0, 'ignored': 0, 'unmapped': []}) + '\n')
    def confirm_file(self, repo, day, mtime):
        os.makedirs(os.path.join(hr.DISPATCH, repo), exist_ok=True)
        p = os.path.join(hr.DISPATCH, repo, 'hours.jsonl')
        open(p, 'w').write(json.dumps({'period': [day, day], 'estimate_h': 1, 'confirmed_h': 1.5, 'note': 'x'}) + '\n')
        os.utime(p, (mtime.timestamp(), mtime.timestamp()))

    def test_picks_report_day_with_no_200_line(self):
        self.report_file('2026-10-20'); self.report_file('2026-10-21')
        self.posted('2026-10-21', datetime(2026, 10, 22, tzinfo=UTC))
        self.assertEqual(hr.catch_up_candidates('2026-10-25'), ['2026-10-20'])

    def test_non_200_lines_do_not_count_and_old_days_are_skipped(self):
        self.report_file('2026-10-20'); self.report_file('2026-08-01')
        with open(hr.POSTED_LOG, 'a') as f:
            f.write(json.dumps({'day': '2026-10-20', 'posted_at': datetime(2026, 10, 21, tzinfo=UTC).isoformat(), 'status': 422}) + '\n')
        self.assertEqual(hr.catch_up_candidates('2026-10-25'), ['2026-10-20'])

    def test_confirmation_newer_than_last_200_reposts(self):
        self.report_file('2026-10-20'); self.report_file('2026-10-21')
        self.posted('2026-10-20', datetime(2026, 10, 21, tzinfo=UTC)); self.posted('2026-10-21', datetime(2026, 10, 22, tzinfo=UTC))
        self.confirm_file('repo-a', '2026-10-20', datetime(2026, 10, 23, tzinfo=UTC))   # after the post
        self.confirm_file('repo-b', '2026-10-21', datetime(2026, 10, 21, tzinfo=UTC))   # before the post
        self.assertEqual(hr.catch_up_candidates('2026-10-25'), ['2026-10-20'])

    def test_catch_up_posts_the_days_and_skips_the_reported_one(self):
        self.write_token()
        self.report_file('2026-10-20'); self.report_file('2026-10-21')
        f = self.serve((200, {'accepted': 1, 'confirmed': 0, 'unmapped': [], 'ignored': 0}))
        calls = []
        orig = hr.gather
        hr.gather = lambda a, day, scan_since=None: (calls.append(day), self.rows())[1]
        self.addCleanup(lambda: setattr(hr, 'gather', orig))
        a = self.args(f.url)
        today = datetime.now(hr.tzinfo(TZ)).date()
        for d in ('2026-10-20', '2026-10-21'):   # relative to a fixed "today" the real clock is far later; use fresh days
            os.remove(os.path.join(hr.REPORTS, d + '.md'))
        fresh = [(today - timedelta(days=n)).isoformat() for n in (1, 2, 3)]
        for d in fresh: self.report_file(d)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            hr.catch_up(a, TOKEN, skip=(fresh[0],))
        self.assertEqual(sorted(calls), sorted(fresh[1:]))
        self.assertEqual(sorted(r['body']['day'] for r in f.requests), sorted(fresh[1:]))
        self.assertEqual(sorted(l['day'] for l in self.log_lines()), sorted(fresh[1:]))

    def test_catch_up_stops_on_a_bad_token(self):
        self.write_token()
        today = datetime.now(hr.tzinfo(TZ)).date()
        for n in (1, 2, 3): self.report_file((today - timedelta(days=n)).isoformat())
        f = self.serve((401, {'error': 'bad token'}))
        orig = hr.gather; hr.gather = lambda a, day, scan_since=None: self.rows()
        self.addCleanup(lambda: setattr(hr, 'gather', orig))
        with contextlib.redirect_stdout(io.StringIO()):
            hr.catch_up(self.args(f.url), TOKEN)
        self.assertEqual(len(f.requests), 1)

if __name__ == '__main__':
    unittest.main()
