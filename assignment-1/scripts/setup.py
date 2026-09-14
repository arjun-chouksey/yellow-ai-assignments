"""Create missing local settings without ever printing secrets."""
from pathlib import Path
import secrets
root = Path(__file__).resolve().parents[1]
p = root / '.env'
text = p.read_text() if p.exists() else (root / '.env.example').read_text()
values = dict(x.split('=', 1) for x in text.splitlines() if x and not x.startswith('#') and '=' in x)
defaults = {'STATE_API_TOKEN': secrets.token_hex(32), 'N8N_ENCRYPTION_KEY': secrets.token_hex(32),
            'GEMINI_MODEL': 'models/gemini-3.1-flash-lite', 'SLACK_SEND_ENABLED': 'false', 'FIXTURE_MODE': 'false'}
for key, value in defaults.items():
    if key not in values:
        text += f'\n{key}={value}\n'
p.write_text(text)
p.chmod(0o600)
print('Local configuration ready; no secrets displayed.')
