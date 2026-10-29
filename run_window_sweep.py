"""Exploratory post-hoc robustness, never used for configuration selection."""
import csv,dataclasses,json
from pathlib import Path
from statistics import mean
from retrybench.model import Scenario
from retrybench.stratcom import make_assessment_workload,simulate_assessment
P=Path(__file__).parent/'results'/'main'
b=json.loads((P/'frozen_parameters.json').read_text())['frozen_adaptive']
rows=[]
for seed in range(91000,91200):
 for template in ['information_environment_assessment','live_fact_check_support','communications_situation_report']:
  w=make_assessment_workload(seed,template)
  for cond in [Scenario('iid',failure_prob=.27,deadline_s=26,mask_outages=True),Scenario('outage',failure_prob=.10,deadline_s=48,use_outages=True,mask_outages=True)]:
   if cond.name=='outage':w1=dataclasses.replace(w,outage_windows=tuple((a,e+2) for a,e in w.outage_windows))
   else:w1=w
   for window in [2.,6.,12.]:
    cfg=dataclasses.replace(cond,adaptive_window_s=window,adaptive_threshold=int(b['threshold']),adaptive_short_s=b['short_s'],adaptive_long_s=b['long_s'])
    met,_=simulate_assessment(w1,cfg,'history_adaptive')
    rows.append({'seed':seed,'template':template,'scenario':cond.name,'window_s':window,'success':int(met.timely_evidence_complete)})
with (P/'history_window_sensitivity.csv').open('w',newline='') as f:
 wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)
with (P/'history_window_summary.csv').open('w',newline='') as f:
 wr=csv.DictWriter(f,fieldnames=['template','scenario','window_s','n','success_pct']);wr.writeheader()
 for temp in ['information_environment_assessment','live_fact_check_support','communications_situation_report']:
  for cond in ['iid','outage']:
   for window in [2.,6.,12.]:
    g=[r for r in rows if r['template']==temp and r['scenario']==cond and r['window_s']==window]
    wr.writerow({'template':temp,'scenario':cond,'window_s':window,'n':len(g),'success_pct':100*mean(r['success'] for r in g)})
