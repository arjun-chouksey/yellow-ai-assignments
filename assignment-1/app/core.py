"""Durable GitHub discovery and delivery support for the visible n8n workflow."""
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class Failure(Exception):
    def __init__(self, message, retry_at=0):
        super().__init__(message)
        self.retry_at = retry_at


def request(method, url, headers, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=25) as res:
            raw = res.read().decode()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw
            return res.status, dict(res.headers.items()), payload
    except HTTPError as exc:
        try:
            payload = json.load(exc)
        except (ValueError, UnicodeError):
            payload = {}
        return exc.code, dict(exc.headers.items()), payload
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        # Do not expose exception text: webhook URLs contain secrets.
        raise Failure('Transport failure; response not confirmed') from None


def qualify(profile):
    return profile['followers'] > 100 or profile['public_repos'] > 50


def normalize(profile):
    for field in ('followers', 'public_repos'):
        if type(profile.get(field)) is not int or profile[field] < 0:
            raise Failure('GitHub profile has invalid numeric fields')
    if not isinstance(profile.get('login'), str):
        raise Failure('GitHub profile is missing login')
    return {key: profile.get(key) for key in
            ('id', 'login', 'name', 'bio', 'company', 'followers', 'public_repos')}


def pitch_text(value):
    if not isinstance(value, str):
        raise Failure('AI response must be text')
    value = value.strip().strip('"')
    if not value or len(value) > 500 or '\n' in value:
        raise Failure('AI pitch must be one short sentence, at most 500 characters')
    # Conservative sentence check; reject and retry rather than truncate the model's claim.
    if re.search(r'[.!?]\s+[A-Z]', value):
        raise Failure('AI pitch contains multiple sentences')
    return value


class Store:
    def __init__(self, path, repo, token='', webhook='', transport=request, clock=time.time,
                 page_size=100, delay=1.0):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ValueError('Invalid repository')
        self.repo, self.token, self.webhook = repo, token, webhook
        self.transport, self.clock, self.delay = transport, clock, delay
        self.page_size = page_size
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS jobs (
            key TEXT PRIMARY KEY, repo TEXT NOT NULL, login TEXT NOT NULL,
            starred_at TEXT NOT NULL, status TEXT NOT NULL, lease TEXT,
            lease_until REAL DEFAULT 0, retry_at REAL DEFAULT 0, attempts INTEGER DEFAULT 0,
            profile TEXT, pitch TEXT, message_id TEXT, error TEXT, is_test INTEGER DEFAULT 0);
        ''')
        if self.get('repo') and self.get('repo') != repo:
            raise ValueError('Use a separate state database when switching repositories')
        self.set('repo', repo)

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))

    def github(self, path):
        if not self.token:
            raise Failure('GITHUB_TOKEN is missing')
        now = self.clock()
        cooldown = self.get('github_retry_at', 0)
        if cooldown > now:
            raise Failure('GitHub cooldown active', cooldown)
        last = self.get('github_last', 0)
        wait = max(0, self.delay - (now - last))
        if wait:
            time.sleep(wait)
        self.set('github_last', self.clock())
        status, headers, data = self.transport('GET', 'https://api.github.com/' + path, {
            'Authorization': 'Bearer ' + self.token,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2026-03-10',
            'User-Agent': 'lead-sniper-assignment'})
        h = {k.lower(): v for k, v in headers.items()}
        self.set('poll_interval', max(60, int(h.get('x-poll-interval', 60))))
        self.set('github_budget', {k: h.get(k) for k in
                 ('x-ratelimit-limit', 'x-ratelimit-remaining', 'x-ratelimit-reset')})
        rate_error = status == 429 or (status == 403 and
            (h.get('x-ratelimit-remaining') == '0' or 'retry-after' in h or
             'rate limit' in str(data.get('message', '')).lower()))
        if rate_error:
            failures = self.get('github_failures', 0) + 1
            self.set('github_failures', failures)
            try:
                resume = self.clock() + max(60, float(h.get('retry-after', 0)),
                                           min(3600, 60 * 2 ** min(failures - 1, 6)))
                if h.get('x-ratelimit-remaining') == '0':
                    resume = max(resume, float(h.get('x-ratelimit-reset', 0)) + 2)
            except (TypeError, ValueError):
                resume = self.clock() + 60
            self.set('github_retry_at', resume)
            raise Failure('GitHub rate limited; work saved for later', resume)
        if status in (401, 403, 404):
            raise Failure(f'GitHub HTTP {status}: verify token and repository access')
        if status != 200:
            raise Failure(f'GitHub HTTP {status}', self.clock() + 60)
        self.set('github_failures', 0)
        return data

    def poll(self):
        # GitHub exposes a bounded public feed: at most 300 events, not all stars.
        now = self.clock()
        next_poll = self.get('next_poll', 0)
        if now < next_poll:
            return {'deferred': True, 'next_poll': next_poll}
        events = []
        for page in range(1, 4):
            data = self.github(f'repos/{self.repo}/events?per_page=100&page={page}')
            if not isinstance(data, list):
                raise Failure('Unexpected event response')
            events.extend(data)
            if len(data) < 100:
                break
        ids = {str(e['id']) for e in events if e.get('id')}
        previous = set(self.get('last_event_ids', []))
        gap = bool(previous and ids and not previous.intersection(ids))
        baseline = not self.get('baseline_complete', False)
        rows = []
        for event in events:
            if event.get('type') != 'WatchEvent' or event.get('payload', {}).get('action') != 'started':
                continue
            actor = event.get('actor', {})
            if not event.get('id') or not re.fullmatch(r'[A-Za-z0-9-]+', actor.get('login', '')) or not event.get('created_at'):
                raise Failure('Star event is missing identity or timestamp')
            if event.get('repo', {}).get('name', '').lower() != self.repo.lower():
                continue
            rows.append((f"{self.repo}:event:{event['id']}", self.repo, actor['login'],
                         event['created_at'], 'baseline' if baseline else 'pending'))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            before = self.db.total_changes
            self.db.executemany('INSERT OR IGNORE INTO jobs(key,repo,login,starred_at,status) VALUES (?,?,?,?,?)', rows)
            added = self.db.total_changes - before
            self.set('baseline_complete', True)
            self.set('last_event_ids', sorted(ids))
            self.set('next_poll', now + self.get('poll_interval', 60))
            self.set('last_poll', now)
            self.set('possible_feed_gap', gap)
            if gap:
                self.set('last_gap_at', now)
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise
        return {'events': len(events), 'star_events': len(rows), 'new_records': added,
                'baseline': baseline, 'possible_feed_gap': gap}

    def replay(self):
        # Explicitly requested demo replay. Original event records are left untouched.
        rows = self.db.execute("SELECT * FROM jobs WHERE is_test=0 ORDER BY starred_at DESC LIMIT 30").fetchall()
        for row in rows:
            profile = normalize(self.github('users/' + row['login']))
            if qualify(profile):
                key = 'test-replay:' + str(uuid.uuid4())
                self.db.execute("INSERT INTO jobs(key,repo,login,starred_at,status,profile,is_test) VALUES (?,?,?,?,'pending',?,1)",
                                (key, self.repo, row['login'], row['starred_at'], json.dumps(profile)))
                return {'key': key, 'test': True, 'login': row['login']}
        raise Failure('No qualifying profile in the 30 latest observed stars; use fixture tests')

    def test_input(self, login):
        if not re.fullmatch(r'[A-Za-z0-9-]+', login):
            raise Failure('Invalid test login')
        profile = normalize(self.github('users/' + login))
        key = 'test-input:' + str(uuid.uuid4())
        self.db.execute("INSERT INTO jobs(key,repo,login,starred_at,status,profile,is_test) VALUES (?,?,?,?,'pending',?,2)",
                        (key, self.repo, login, datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(), json.dumps(profile)))
        return {'key': key, 'test': True, 'qualifies': qualify(profile)}

    def claim(self):
        now = self.clock()
        self.db.execute("UPDATE jobs SET status='failed',error='Retry limit reached' WHERE status='working' AND lease_until<=? AND attempts>=5", (now,))
        # Only one active job; sending is never automatically reclaimed after a crash.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute("UPDATE jobs SET status='unknown', error='Interrupted delivery; inspect channel before retry' WHERE status='sending' AND lease_until<=?", (now,))
            busy = self.db.execute("SELECT 1 FROM jobs WHERE status IN ('working','sending') AND lease_until>?", (now,)).fetchone()
            row = None if busy else self.db.execute("SELECT * FROM jobs WHERE (status='pending' OR (status='working' AND lease_until<=?)) AND retry_at<=? AND attempts<5 ORDER BY starred_at,key LIMIT 1", (now, now)).fetchone()
            if row:
                lease = str(uuid.uuid4())
                self.db.execute("UPDATE jobs SET status='working',lease=?,lease_until=?,attempts=attempts+1 WHERE key=?", (lease, now + 600, row['key']))
                result = dict(row)
                result.update(available=True, lease=lease)
                result['profile'] = json.loads(result['profile']) if result['profile'] else None
            else:
                result = {'available': False}
            self.db.execute('COMMIT')
            return result
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def job(self, key, lease):
        row = self.db.execute("SELECT * FROM jobs WHERE key=? AND lease=? AND status='working' AND lease_until>?", (key, lease, self.clock())).fetchone()
        if not row:
            raise Failure('Job lease expired or already completed')
        return dict(row)

    def profile(self, key, lease):
        row = self.job(key, lease)
        profile = json.loads(row['profile']) if row['profile'] else normalize(self.github('users/' + row['login']))
        self.db.execute('UPDATE jobs SET profile=? WHERE key=?', (json.dumps(profile), key))
        return {'key': key, 'lease': lease, 'repo': self.repo, 'profile': profile, 'pitch': row['pitch']}

    def reject(self, key, lease):
        row = self.job(key, lease)
        if not row['profile'] or qualify(json.loads(row['profile'])):
            raise Failure('Cannot reject a qualifying or unenriched profile')
        self.db.execute("UPDATE jobs SET status='rejected',lease=NULL WHERE key=?", (key,))
        return {'status': 'rejected'}

    def fail(self, key, lease, message='Workflow step failed', retry_at=0):
        row = self.job(key, lease)
        terminal = row['attempts'] >= 5
        self.db.execute('UPDATE jobs SET status=?,error=?,retry_at=?,lease=NULL WHERE key=?',
                        ('failed' if terminal else 'pending', message[:200],
                         max(retry_at, self.clock() + min(3600, 60 * 2 ** row['attempts'])), key))
        return {'status': 'failed' if terminal else 'pending'}

    def deliver(self, key, lease, pitch):
        row = self.job(key, lease)
        if not row['profile'] or not qualify(json.loads(row['profile'])):
            raise Failure('Cannot deliver an unqualified profile')
        pitch = pitch_text(pitch)
        if not self.webhook:
            raise Failure('Slack delivery not configured or enabled')
        p = json.loads(row['profile'])
        reasons = []
        if p['followers'] > 100:
            reasons.append(f"{p['followers']} followers (>100)")
        if p['public_repos'] > 50:
            reasons.append(f"{p['public_repos']} public repos (>50)")
        title = ('[TEST INPUT] ' if row['is_test'] == 2 else '[TEST REPLAY] ' if row['is_test'] else '') + 'High-value GitHub lead'
        fields = [
            {'type': 'plain_text', 'text': 'Name: ' + (p['name'] or p['login'])[:200]},
            {'type': 'plain_text', 'text': 'Company: ' + (p['company'] or 'Not provided')[:200]},
            {'type': 'plain_text', 'text': 'Qualified: ' + ' OR '.join(reasons)},
            {'type': 'plain_text', 'text': 'Repository: ' + self.repo}]
        payload = {'text': title, 'unfurl_links': False, 'unfurl_media': False,
                   'blocks': [
                       {'type': 'header', 'text': {'type': 'plain_text', 'text': title}},
                       {'type': 'section', 'fields': fields},
                       {'type': 'section', 'text': {'type': 'plain_text', 'text': 'Bio: ' + (p['bio'] or 'Not provided')[:1000]}},
                       {'type': 'section', 'text': {'type': 'plain_text', 'text': 'AI outreach rationale: ' + pitch}},
                       {'type': 'context', 'elements': [{'type': 'plain_text', 'text': 'https://github.com/' + p['login'] + ' | ' + key}]}]}
        self.db.execute("UPDATE jobs SET status='sending',pitch=? WHERE key=?", (pitch, key))
        try:
            status, headers, data = self.transport('POST', self.webhook,
                                                  {'Content-Type': 'application/json'}, payload)
        except Failure:
            self.db.execute("UPDATE jobs SET status='unknown',error='Delivery response missing; inspect channel' WHERE key=?", (key,))
            return {'status': 'unknown'}
        if status == 429:
            try:
                delay = max(1, float({k.lower(): v for k, v in headers.items()}.get('retry-after', 60)))
            except (ValueError, TypeError):
                delay = 60
            self.db.execute("UPDATE jobs SET status='pending',retry_at=?,lease=NULL WHERE key=?", (self.clock() + delay, key))
            return {'status': 'pending', 'retry_after': delay}
        if status == 200 and data == 'ok':
            state, message_id = 'sent', None
        elif 400 <= status < 500:
            state, message_id = 'failed', None
        else:
            state, message_id = 'unknown', None
        self.db.execute('UPDATE jobs SET status=?,message_id=?,error=?,lease=NULL WHERE key=?',
                        (state, message_id, None if state == 'sent' else f'Slack HTTP {status}; inspect before retry', key))
        return {'status': state, 'message_id': message_id}

    def status(self):
        return {'repo': self.repo, 'baseline_complete': self.get('baseline_complete', False),
                'last_poll': self.get('last_poll'), 'possible_feed_gap': self.get('possible_feed_gap', False), 'last_gap_at': self.get('last_gap_at'), 'github_budget': self.get('github_budget'),
                'counts': dict(self.db.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status').fetchall())}
