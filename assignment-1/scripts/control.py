"""Access the internal API through Docker; never prints credentials."""
import subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
actions={'status':('GET','/status'),'poll':('POST','/poll'),'replay':('POST','/replay'),'seed-fixtures':('POST','/fixture/seed')}
if len(sys.argv)!=2 or sys.argv[1] not in actions: raise SystemExit('Usage: control.py status|poll|replay|seed-fixtures')
method,path=actions[sys.argv[1]]
code="import os,json,urllib.request; r=urllib.request.Request('http://localhost:8080"+path+"', data="+('None' if method=='GET' else "b'{}'")+", headers={'Authorization':'Bearer '+os.environ['STATE_API_TOKEN'],'Content-Type':'application/json'},method='"+method+"')\ntry:\n print(urllib.request.urlopen(r).read().decode())\nexcept urllib.error.HTTPError as e:\n print(e.read().decode()); raise SystemExit(1)"
result=subprocess.run(['docker','compose','exec','-T','state','python','-c',code],cwd=root)
raise SystemExit(result.returncode)
