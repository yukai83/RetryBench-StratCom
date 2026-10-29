"""Label-masking control (Table I): the same outages with the cause visible to the policy or masked as a generic 5xx.

Run: python run_label_masking.py [output-directory]
All draws, DAGs and seeds are shared across policies.
"""
from __future__ import annotations
import csv, json, sys
from dataclasses import replace
from pathlib import Path
import numpy as np
from retrybench.stratcom import TEMPLATES, make_assessment_workload, simulate_assessment
from retrybench.scenarios import MAIN_SCENARIOS

OUT=Path(sys.argv[1] if len(sys.argv)>1 else Path(__file__).parent/'results'/'label_masking')
OUT.mkdir(parents=True,exist_ok=True)
POLS=('immediate','exponential','budget_aware','cooldown_only','observable_cooldown')
LOOKUP={s.name:s for s in MAIN_SCENARIOS}
SCENARIOS={
 'outage_labeled':LOOKUP['outage_45'],
 'outage_hidden_5xx':replace(LOOKUP['outage_45'], name='outage_hidden_5xx', mask_outages=True),
 'iid_tight_15':LOOKUP['iid_tight_15'],
 'iid_medium_20':LOOKUP['iid_medium_20'],
 'rate_limit_hinted':LOOKUP['rate_limit_hinted']
}
SEEDS=range(2026,2226)
rows=[]
for template in TEMPLATES:
    for seed in SEEDS:
        workload=make_assessment_workload(seed,template)
        for sn,sc in SCENARIOS.items():
            for pol in POLS:
                m,r=simulate_assessment(workload,sc,pol)
                rows.append(dict(template=template,scenario=sn,policy=pol,seed=seed,
                    fresh=int(m.timely_evidence_complete),delivered=int(m.brief_delivered),
                    calls=m.calls,retries=m.retries,elapsed_s=round(m.elapsed_s,6),
                    outage_errors=r.outage_errors))

def save(path,data):
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
save(OUT/'label_masking_trials.csv', rows)
by={(r['template'],r['scenario'],r['policy'],r['seed']):r for r in rows}
assert len(by)==len(rows)
summary=[]
for t in TEMPLATES:
    for sn in SCENARIOS:
        for pol in POLS:
            r=[by[t,sn,pol,s] for s in SEEDS]
            summary.append(dict(template=t,scenario=sn,policy=pol,n=len(r),fresh_pct=round(100*np.mean([a['fresh'] for a in r]),3),
                delivered_pct=round(100*np.mean([a['delivered'] for a in r]),3),
                mean_calls=round(float(np.mean([a['calls'] for a in r])),5),
                mean_latency_s=round(float(np.mean([a['elapsed_s'] for a in r])),5)))
save(OUT/'label_masking_summary.csv',summary)
idx=np.random.default_rng(20261023).integers(0,200,size=(4000,200))
contrasts=[]
# two contrasts matter for the information asymmetry and one benchmarks a more conservative observable policy
for t in TEMPLATES:
  for sn in SCENARIOS:
    for a,b in [('budget_aware','immediate'),('budget_aware','exponential'),('observable_cooldown','budget_aware'),('observable_cooldown','exponential'),('observable_cooldown','cooldown_only')]:
      diff=np.array([by[t,sn,a,s]['fresh']-by[t,sn,b,s]['fresh'] for s in SEEDS],dtype=float)
      lo,hi=np.percentile(diff[idx].mean(axis=1),[2.5,97.5])
      contrasts.append(dict(template=t,scenario=sn,policy_a=a,policy_b=b,n=200,delta_pp=round(100*diff.mean(),3),lo95_pp=round(100*lo,3),hi95_pp=round(100*hi,3),
          positive=int(sum(diff>0)),negative=int(sum(diff<0)),ties=int(sum(diff==0))))
save(OUT/'label_masking_paired_contrasts.csv',contrasts)
# The masking experiment may change policy decisions, but does not change exogenous workload.
for t in TEMPLATES:
    for pol in ('immediate','exponential'):
        for seed in SEEDS:
            a,b=by[t,'outage_labeled',pol,seed],by[t,'outage_hidden_5xx',pol,seed]
            assert (a['fresh'],a['delivered'],a['calls'],a['elapsed_s'])==(b['fresh'],b['delivered'],b['calls'],b['elapsed_s'])
manifest={'study':'observable-error challenge to latent outage oracle','simulation_only':True,
 'policies':list(POLS),'scenarios':list(SCENARIOS),'n_per_cell':200,'cells':len(summary),
 'total_trials':len(rows),'seeds':[min(SEEDS),max(SEEDS)],'paired_bootstrap_resamples':4000,
 'policy_interpretation':'outage_hidden_5xx changes only the error label exposed to the policy; ground-truth failure class retained for auditing; observable_cooldown does not use hidden outage labels',
 'important_limitation':'No external API/LLM evidence or independently measured trace calibration'}
(OUT/'label_masking_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print('Completed',len(rows),'trials')
for t in TEMPLATES:
    print('\n',t)
    for sn in ('outage_labeled','outage_hidden_5xx','iid_tight_15','iid_medium_20'):
        print(sn,{r['policy']:r['fresh_pct'] for r in summary if r['template']==t and r['scenario']==sn})
