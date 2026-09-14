import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from core import Store,Failure,qualify,normalize,pitch_text

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.now=1800000000.;self.responses=[];self.calls=[]
  def transport(*args):
   self.calls.append(args)
   result=self.responses.pop(0)
   if isinstance(result,Exception):raise result
   return result
  self.store=Store(str(Path(self.tmp.name)/'state.db'),'n8n-io/n8n','test','https://hooks.slack.com/services/T/B/test',transport=transport,clock=lambda:self.now,delay=0)
 def tearDown(self):self.store.db.close();self.tmp.cleanup()
 def event(self,id,stamp='2026-09-01T00:00:00Z'):
  return {'id':str(id),'type':'WatchEvent','payload':{'action':'started'},'actor':{'login':'example'},'repo':{'name':'n8n-io/n8n'},'created_at':stamp}
 def seed(self,followers=101,repos=0):
  self.store.db.execute("INSERT INTO jobs(key,repo,login,starred_at,status) VALUES('job','n8n-io/n8n','example','2026-09-01','pending')")
  job=self.store.claim();self.responses.append((200,{},dict(login='example',name=None,bio=None,company=None,followers=followers,public_repos=repos)))
  self.store.profile(job['key'],job['lease']);return job
 def test_boundaries(self):
  for f,r,want in [(100,50,False),(101,0,True),(0,51,True),(0,0,False),(101,51,True)]:
   self.assertEqual(qualify({'followers':f,'public_repos':r}),want)
 def test_invalid_profile(self):
  for value in [None,'101',True,-1]:
   with self.assertRaises(Failure):normalize({'login':'a','followers':value,'public_repos':0})
 def test_baseline_and_delayed_event_dedup(self):
  self.responses=[(200,{},[self.event(1)])];self.store.poll();self.assertFalse(self.store.claim()['available'])
  self.now+=61;self.responses=[(200,{},[self.event(1),self.event(2,'2026-08-31T00:00:00Z')])];self.store.poll()
  self.assertEqual(self.store.status()['counts'],{'baseline':1,'pending':1})
  self.now+=61;self.responses=[(200,{},[self.event(2),self.event(1)])];self.store.poll()
  self.assertEqual(self.store.status()['counts']['pending'],1)
 def test_poll_interval(self):
  self.responses=[(200,{'X-Poll-Interval':'120'},[])];self.store.poll();self.now+=61
  self.assertTrue(self.store.poll()['deferred']);self.assertEqual(len(self.calls),1)
 def test_pages_atomic_on_failure(self):
  self.responses=[(200,{},[self.event(i) for i in range(100)]),(503,{}, {})]
  with self.assertRaises(Failure):self.store.poll()
  self.assertEqual(self.store.status()['counts'],{});self.assertFalse(self.store.get('baseline_complete'))
 def test_three_pages(self):
  self.responses=[(200,{},[self.event(i+j*100) for i in range(100)]) for j in range(3)]
  self.assertEqual(self.store.poll()['events'],300)
 def test_feed_gap(self):
  self.responses=[(200,{},[self.event(1)])];self.store.poll();self.now+=61
  self.responses=[(200,{},[self.event(2)])];self.assertTrue(self.store.poll()['possible_feed_gap'])
 def test_rate_reset(self):
  self.responses=[(403,{'X-RateLimit-Remaining':'0','X-RateLimit-Reset':str(self.now+500)}, {})]
  with self.assertRaises(Failure) as e:self.store.github('user')
  self.assertGreaterEqual(e.exception.retry_at,self.now+500)
  with self.assertRaises(Failure):self.store.github('user')
  self.assertEqual(len(self.calls),1)
 def test_permission_not_rate_limit(self):
  self.responses=[(403,{'X-RateLimit-Remaining':'4000'},{'message':'Resource not accessible'})]
  with self.assertRaises(Failure) as e:self.store.github('user')
  self.assertEqual(e.exception.retry_at,0)
 def test_secondary_retry_after(self):
  self.responses=[(429,{'Retry-After':'240'}, {})]
  with self.assertRaises(Failure) as e:self.store.github('user')
  self.assertGreaterEqual(e.exception.retry_at,self.now+240)
 def test_single_lease_and_restart(self):
  j=self.seed();self.assertFalse(self.store.claim()['available']);self.now+=601
  j2=self.store.claim();self.assertNotEqual(j['lease'],j2['lease'])
  with self.assertRaises(Failure):self.store.job(j['key'],j['lease'])
 def test_reject(self):
  j=self.seed(100,50);self.assertEqual(self.store.reject(j['key'],j['lease'])['status'],'rejected')
 def test_cannot_deliver_rejected(self):
  j=self.seed(100,50)
  with self.assertRaises(Failure):self.store.deliver(j['key'],j['lease'],'A relevant prospect.')
 def test_slack_success_and_no_resend(self):
  j=self.seed();self.responses=[(200,{},'ok')]
  self.assertEqual(self.store.deliver(j['key'],j['lease'],'Their AI interest may be relevant.')['status'],'sent')
  self.assertFalse(self.store.claim()['available'])
  with self.assertRaises(Failure):self.store.deliver(j['key'],j['lease'],'Their AI interest may be relevant.')
 def test_uncertain_delivery(self):
  j=self.seed();self.responses=[Failure('timeout')]
  self.assertEqual(self.store.deliver(j['key'],j['lease'],'Relevant interest.')['status'],'unknown')
  self.now+=700;self.assertFalse(self.store.claim()['available'])
 def test_slack_throttle_caches_pitch(self):
  j=self.seed();self.responses=[(429,{'Retry-After':'90'},'rate_limited')]
  self.assertEqual(self.store.deliver(j['key'],j['lease'],'Relevant interest.')['status'],'pending')
  self.assertFalse(self.store.claim()['available']);self.now+=91
  j2=self.store.claim();self.assertEqual(j2['pitch'],'Relevant interest.')
 def test_crashed_sending_not_replayed(self):
  j=self.seed();self.store.db.execute("UPDATE jobs SET status='sending'");self.now+=601
  self.assertFalse(self.store.claim()['available']);self.assertEqual(self.store.status()['counts'],{'unknown':1})
 def test_retry_exhaustion(self):
  self.seed();self.store.db.execute('UPDATE jobs SET attempts=5');self.now+=601
  self.assertFalse(self.store.claim()['available']);self.assertEqual(self.store.status()['counts'],{'failed':1})
 def test_pitch_validation(self):
  for p in ['',None,'a\nb','First sentence. Second sentence.','a'*501]:
   with self.assertRaises(Failure):pitch_text(p)
 def test_plain_text_slack_fields(self):
  j=self.seed();self.responses=[(200,{},'ok')];self.store.deliver(j['key'],j['lease'],'Consider <!channel> as untrusted text.')
  payload=self.calls[-1][3]
  self.assertEqual(payload['blocks'][3]['text']['type'],'plain_text')

if __name__=='__main__':unittest.main()
