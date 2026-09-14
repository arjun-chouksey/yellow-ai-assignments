"""Import workflow and credentials via stdin; no secret files or command arguments."""
import json
import subprocess
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
v = dict(x.split('=',1) for x in (root/'.env').read_text().splitlines() if x and not x.startswith('#') and '=' in x)
fixture = '--fixture' in sys.argv
credentials = [
 {'id':'lead-sniper-state','name':'Lead Sniper State','type':'httpHeaderAuth','data':{'name':'Authorization','value':'Bearer '+v['STATE_API_TOKEN']}},
 {'id':'lead-sniper-gemini','name':'Lead Sniper Gemini','type':'googlePalmApi','data':{'apiKey':'fixture' if fixture else v.get('GEMINI_API_KEY',''), 'host':'http://state:8080/gemini' if fixture else 'https://generativelanguage.googleapis.com'}}]
def import_data(payload,kind):
    # /tmp is inside the local container and removed immediately, even on failure.
    cmd=['docker','compose','exec','-T','n8n','sh','-c',f'umask 077; cat > /tmp/lead-sniper-import.json; n8n import:{kind} --input=/tmp/lead-sniper-import.json; result=$?; rm -f /tmp/lead-sniper-import.json; exit "$result"']
    r=subprocess.run(cmd,input=json.dumps(payload),text=True,cwd=root,capture_output=True)
    if r.returncode:
        print('Import failed. Check n8n startup and permissions; output suppressed to protect credentials.')
        raise SystemExit(1)
import_data(credentials,'credentials')
w=json.loads((root/'workflows'/'lead-sniper.json').read_text())
for n in w['nodes']:
    if n['name']=='Gemini Chat Model': n['parameters']['modelName']=v.get('GEMINI_MODEL','models/gemini-3.1-flash-lite')
import_data([w],'workflow')
print('Credentials and inactive workflow imported. Restart n8n to refresh its view.')
