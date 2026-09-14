"""Internal-only state API. No host port is exposed by Compose."""
import hmac
import json
import os
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from core import Store, Failure


def main():
    secret = os.environ['STATE_API_TOKEN']
    mode = os.getenv('FIXTURE_MODE', 'false') == 'true'
    store = Store(os.getenv('STATE_DB', '/data/lead-sniper.sqlite'),
                  os.getenv('GITHUB_REPOSITORY', 'n8n-io/n8n'),
                  token=os.getenv('GITHUB_TOKEN', ''),
                  webhook=os.getenv('SLACK_WEBHOOK_URL', '') if os.getenv('SLACK_SEND_ENABLED') == 'true' else '')
    if store.webhook and not re.fullmatch(r'https://hooks\.slack\.com/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9]+', store.webhook):
        raise ValueError('Use a Slack webhook URL without query parameters')
    if mode:
        from fixtures import transport
        store.transport, store.token, store.webhook, store.delay = transport, 'fixture', 'https://hooks.slack.com/services/T/B/fixture', 0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, value):
            data = json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/health':
                return self.reply(200, {'ok': True, 'fixture_mode': mode})
            if not self.authorized():
                return self.reply(401, {'error': 'Unauthorized'})
            if self.path == '/status':
                return self.reply(200, store.status())
            self.reply(404, {'error': 'Unknown route'})

        def authorized(self):
            return hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + secret)

        def do_POST(self):
            size = int(self.headers.get('Content-Length', 0))
            if size > 32768:
                return self.reply(413, {'error': 'Request too large'})
            # Fixture Gemini is only reachable inside the isolated test network.
            if mode and self.path.startswith('/gemini/'):
                self.rfile.read(size)
                return self.reply(200, {'candidates': [{'content': {'role': 'model', 'parts': [{'text': 'Their stated interest in AI makes a discussion about support automation potentially relevant.'}]}, 'finishReason': 'STOP'}], 'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 18, 'totalTokenCount': 28}})
            if not self.authorized():
                return self.reply(401, {'error': 'Unauthorized'})
            try:
                body = json.loads(self.rfile.read(size) or b'{}')
                if self.path == '/poll':
                    result = store.poll()
                elif self.path == '/test-input' and os.getenv('ALLOW_TEST_INPUT') == 'true':
                    result = store.test_input(body['login'])
                elif self.path == '/replay':
                    result = store.replay()
                elif self.path == '/claim':
                    result = store.claim()
                elif self.path == '/profile':
                    result = store.profile(body['key'], body['lease'])
                elif self.path == '/reject':
                    result = store.reject(body['key'], body['lease'])
                elif self.path == '/deliver':
                    result = store.deliver(body['key'], body['lease'], body['pitch'])
                elif self.path == '/fail':
                    result = store.fail(body['key'], body['lease'])
                elif mode and self.path == '/fixture/seed':
                    store.db.executemany("INSERT OR IGNORE INTO jobs(key,repo,login,starred_at,status) VALUES (?,?,?,?, 'pending')", [
                        ('fixture-qualified', store.repo, 'fixture-qualified', '2026-01-01T00:00:00Z'),
                        ('fixture-rejected', store.repo, 'fixture-rejected', '2026-01-01T00:00:01Z')])
                    result = {'fixture': True, 'seeded': True}
                else:
                    return self.reply(404, {'error': 'Unknown route'})
                self.reply(200, result)
            except Failure as exc:
                if self.path in ('/profile', '/deliver'):
                    try:
                        store.fail(body['key'], body['lease'], str(exc), exc.retry_at)
                    except Failure:
                        pass
                self.reply(422, {'error': str(exc), 'retry_at': exc.retry_at})
            except (KeyError, ValueError, TypeError):
                self.reply(400, {'error': 'Invalid request'})
            except Exception:
                self.reply(500, {'error': 'Internal state error; inspect local service'})

    HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()


if __name__ == '__main__':
    main()
