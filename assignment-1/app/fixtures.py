"""Deterministic test doubles, never used unless FIXTURE_MODE=true."""

def transport(method, url, headers, body=None):
    if '/events?' in url:
        return 200, {}, []
    if '/users/' in url:
        login = url.rsplit('/', 1)[-1]
        return 200, {}, {'id': 1, 'login': login, 'name': 'Fixture User',
                          'bio': 'Interested in AI and open source', 'company': None,
                          'followers': 120 if login == 'fixture-qualified' else 100,
                          'public_repos': 50}
    if method == 'POST' and 'hooks.slack.com' in url:
        return 200, {}, 'ok'
    raise AssertionError('Unexpected fixture request')
