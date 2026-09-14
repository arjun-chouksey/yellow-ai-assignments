"""Execute the real n8n workflow and print only a concise, secret-free result."""
import json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
r=subprocess.run(['docker','compose','exec','-T','-e','N8N_RUNNERS_BROKER_PORT=5681','n8n','n8n','execute','--id=lead-sniper-main'],cwd=root,capture_output=True,text=True)
s=r.stdout
marker='===================================='
try:
 d=json.loads(s.split(marker,1)[1].strip()); data=d['data']['resultData']; summary={'status':d.get('status'),'last_node':data.get('lastNodeExecuted'),'nodes':{}}
 for name,runs in data.get('runData',{}).items():
  summary['nodes'][name]=[{'status':x.get('executionStatus'),'outputs':[len(a or []) for a in x.get('data',{}).get('main',[])]} for x in runs]
  if name in ['Poll Public Star Events','Send Slack Alert','Record Rejection','Save AI Failure for Retry']:
   summary['nodes'][name]=[{'result':item['json']} for run in runs for branch in run.get('data',{}).get('main',[]) for item in (branch or [])]
 print(json.dumps(summary,indent=2))
except (ValueError,KeyError,IndexError):
 print('n8n returned no execution result. Exit code:',r.returncode)
 # Never dump unfiltered n8n errors; URLs and credentials can be embedded.
raise SystemExit(r.returncode)
