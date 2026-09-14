"""Queue a clearly labeled simulated event with a real GitHub profile."""
import subprocess,sys,json
from pathlib import Path
if len(sys.argv)!=2:raise SystemExit('Usage: test_input.py GITHUB_LOGIN')
code="import os,json,urllib.request; r=urllib.request.Request('http://localhost:8080/test-input',data="+repr(json.dumps({'login':sys.argv[1]}).encode())+",headers={'Authorization':'Bearer '+os.environ['STATE_API_TOKEN'],'Content-Type':'application/json'},method='POST'); print(urllib.request.urlopen(r).read().decode())"
r=subprocess.run(['docker','compose','exec','-T','state','python','-c',code],cwd=Path(__file__).resolve().parents[1])
raise SystemExit(r.returncode)
