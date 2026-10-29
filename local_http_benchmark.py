"""Actual localhost HTTP client/server fault injection (not production traces).
Unseen cases use fixed seed IDs, no post-hoc tuning. Runs in wall-clock time.
"""
from pathlib import Path
import csv,hashlib,json,threading,time,urllib.request,urllib.error,urllib.parse,statistics
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from retrybench.policies import RetryContext,decide
ROOT=Path(__file__).parent/'results'/'main'
SCALE=.035  # 1 simulated second = 35 ms real time; documented acceleration.
SEEDS=range(221000,221016)
POLICIES=('immediate','exponential','observable_cooldown','sdk_style_proxy','history_adaptive')
REGIMES=('iid_http_503','brief_http_503_outage','shared_http_429','timeout_http')

class Environment:
 def __init__(self):self.lock=threading.Lock();self.reset('iid_http_503',0)
 def reset(self,mode,seed):
  with self.lock if hasattr(self,'lock') else _null():
   self.mode,self.seed,self.t0,self.calls,self.tokens,self.last=mode,seed,time.monotonic(),0,1.0,time.monotonic()

class _null:
 def __enter__(self):pass
 def __exit__(self,*args):pass

def u01(*args):
 h=hashlib.blake2b('|'.join(map(str,args)).encode(),digest_size=8).digest()
 return int.from_bytes(h,'little')/(2**64)

E=Environment()
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  v=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
  task=int(v.get('task',['0'])[0]);attempt=int(v.get('attempt',['1'])[0]);now=time.monotonic()
  with E.lock:
   E.calls+=1; elapsed=(now-E.t0)/SCALE;mode=E.mode; seed=E.seed
   if mode=='shared_http_429':
    E.tokens=min(1.0,E.tokens+(now-E.last)/(.9*SCALE));E.last=now
    throttled=E.tokens<.999
    if not throttled:E.tokens-=1
   else:throttled=False
  status=200; sleep_s=.003; retryafter=None
  if mode=='iid_http_503' and u01(seed,task,attempt,'iid')<.27:status=503
  if mode=='brief_http_503_outage' and elapsed < 3.3:status=503
  if mode=='shared_http_429' and throttled:
   status=429;retryafter=1
  if mode=='timeout_http' and u01(seed,task,attempt,'timeout')<.20:
   sleep_s=.085
  time.sleep(sleep_s)
  try:
   self.send_response(status)
   if retryafter is not None:self.send_header('Retry-After',str(retryafter))
   self.end_headers()
   self.wfile.write(b'{}')
  except (BrokenPipeError,ConnectionResetError):pass
 def log_message(self,*args):pass

def one(base,policy,mode,seed,params):
 E.reset(mode,seed)
 started=time.monotonic();deadline=12 if mode=='brief_http_503_outage' else 13
 calls=0;errors=[];success=True
 for task in range(3):
  done=False
  for attempt in range(1,5):
   now=(time.monotonic()-started)/SCALE
   if now>=deadline:break
   calls+=1
   try:
    with urllib.request.urlopen(base+f'?task={task}&attempt={attempt}',timeout=.050) as resp: resp.read()
    status=200;hint=None
   except urllib.error.HTTPError as er:
    status=er.code;hint=float(er.headers['Retry-After']) if 'Retry-After' in er.headers else None
   except (TimeoutError,urllib.error.URLError):
    status=0;hint=None
   now=(time.monotonic()-started)/SCALE
   errors.append((now,'success' if status==200 else ('rate_limit' if status==429 else 'transient' if status==503 else 'timeout')))
   errors=[(t,e) for t,e in errors if now-t<=6.]
   if status==200:done=True;break
   error='rate_limit' if status==429 else ('transient' if status==503 else 'timeout')
   ctx=RetryContext(error=error,attempt_count=attempt,max_attempts=4,now=now,deadline=deadline,
    calls_so_far=calls,task_count=3,longest_remaining_chain=3-task,jitter=1.,retry_after_s=hint,
    recent_errors=sum(e in ('transient','timeout') for t,e in errors),recent_total=len(errors),
    adaptive_threshold=int(params['threshold']),adaptive_short_s=params['short_s'],adaptive_long_s=params['long_s'])
   if policy=='observable_cooldown':ctx=__import__('dataclasses').replace(ctx,observable_cooldown_factor=1.5)
   dec=decide(policy,ctx)
   if not dec.retry or now+dec.delay_s>=deadline:break
   time.sleep(dec.delay_s*SCALE)
  if not done:success=False;break
 elapsed=(time.monotonic()-started)/SCALE
 return {'regime':mode,'policy':policy,'seed':seed,'success':int(success and elapsed<=deadline),
  'elapsed_virtual_s':round(elapsed,4),'calls':calls,'deadline_virtual_s':deadline}

if __name__=='__main__':
 params=json.loads((ROOT/'frozen_parameters.json').read_text())['frozen_adaptive']
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
 t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
 base=f'http://127.0.0.1:{server.server_port}/work'
 rows=[]
 try:
  for regime in REGIMES:
   for seed in SEEDS:
    for policy in POLICIES:
     rows.append(one(base,policy,regime,seed,params))
 finally:
  server.shutdown();server.server_close();t.join(timeout=2.)
 with (ROOT/'localhost_http_trials.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 stat=[]
 for regime in REGIMES:
  for policy in POLICIES:
   v=[r for r in rows if r['regime']==regime and r['policy']==policy]
   stat.append({'regime':regime,'policy':policy,'n':len(v),'success_pct':100*statistics.mean(x['success'] for x in v),
     'mean_calls':round(statistics.mean(x['calls'] for x in v),2),'mean_virtual_elapsed_s':round(statistics.mean(x['elapsed_virtual_s'] for x in v),2)})
 with (ROOT/'localhost_http_summary.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(stat[0]));w.writeheader();w.writerows(stat)
 print(json.dumps(stat,indent=2))
