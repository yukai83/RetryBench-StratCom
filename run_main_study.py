"""Main study: development tuning, frozen configuration, held-out and unseen-graph comparisons.
No held-out result is used to change the configuration. Synthetic results only.
"""
import csv,json,dataclasses,collections
from pathlib import Path
from statistics import mean
import numpy as np
from retrybench.model import Scenario,generate_workload
from retrybench.stratcom import make_assessment_workload,simulate_assessment
from retrybench.simulator import simulate

OUT=Path(__file__).parent/'results'/'main';OUT.mkdir(parents=True,exist_ok=True)
TEMPLATES=['information_environment_assessment','live_fact_check_support','communications_situation_report']
BASELINES=('immediate','exponential','observable_cooldown','sdk_style_proxy','history_adaptive')

# Development set. Before any held-out evaluation, tune only 3 disclosed knobs.
# Fixed time-window = 6 seconds. Objective = pooled fresh delivery over three
# templates and three failure regimes, 40 predetermined development seeds.
def develop():
    devseeds=list(range(61100,61140))
    devcases=[Scenario('dev_iid',failure_prob=.22,deadline_s=22,mask_outages=True),
              Scenario('dev_outage',failure_prob=.07,deadline_s=45,use_outages=True,mask_outages=True),
              Scenario('dev_quota',failure_prob=.08,deadline_s=55,provider_rps=1.8,burst_tokens=2,advertise_retry_after=True,mask_outages=True)]
    configs=[(th,short,long) for th in (2,3) for short in (.20,.40) for long in (1.,1.5,2.)]
    records=[]
    for th,short,long in configs:
        y=[]; calls=[]
        for seed in devseeds:
            for template in TEMPLATES:
                w=make_assessment_workload(seed,template)
                for sc in devcases:
                    cfg=dataclasses.replace(sc, adaptive_threshold=th,adaptive_short_s=short,adaptive_long_s=long)
                    m,_=simulate_assessment(w,cfg,'history_adaptive')
                    y.append(m.timely_evidence_complete);calls.append(m.calls)
        records.append({'threshold':th,'short_s':short,'long_s':long,'n':len(y),
                        'score':mean(y),'mean_calls':mean(calls)})
    records.sort(key=lambda x:(-x['score'],x['mean_calls'],x['threshold'],x['long_s']))
    write_csv(OUT/'development_grid.csv',records)
    best=records[0]
    (OUT/'frozen_parameters.json').write_text(json.dumps({'selection_criterion':'Highest pooled fresh-delivery rate over 3 templates x 3 scenarios x 40 development seeds; tie-break fewer calls',
         'development_seeds':'61100..61139','test_seeds':'91000..91199; 140000..140119 for unseen generic DAGs',
         'frozen_adaptive':best, 'grid':{'threshold':[2,3],'short_s':[.2,.4],'long_s':[1.,1.5,2.]},
         'not_real_world_calibration':True},indent=2))
    return best

def write_csv(file,rows):
    with file.open('w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def test(best):
    scenarios=[Scenario('held_iid_27',failure_prob=.27,deadline_s=26,mask_outages=True),
      Scenario('held_outage_extended',failure_prob=.10,deadline_s=48,use_outages=True,mask_outages=True),
      Scenario('held_tight_17',failure_prob=.17,deadline_s=14,mask_outages=True),
      Scenario('held_quota_23',failure_prob=.09,deadline_s=52,provider_rps=2.3,burst_tokens=2,advertise_retry_after=True,mask_outages=True),
      Scenario('held_mixed',failure_prob=.2,permanent_prob=.02,deadline_s=40,mask_outages=True)]
    rows=[]
    for seed in range(91000,91200):
        for temp in TEMPLATES:
            w=make_assessment_workload(seed,temp)
            for base in scenarios:
                # Longer outage windows for test domain shift; same modification
                # to all policies under the matched seed.
                ww=(dataclasses.replace(w,outage_windows=tuple((a,b+2.) for a,b in w.outage_windows))
                    if base.name=='held_outage_extended' else w)
                cfg=dataclasses.replace(base,adaptive_threshold=int(best['threshold']),
                  adaptive_short_s=best['short_s'], adaptive_long_s=best['long_s'])
                for pol in BASELINES:
                    m,_=simulate_assessment(ww,cfg,pol)
                    rows.append({'split':'held_out','seed':seed,'template':temp,'scenario':base.name,'policy':pol,
                      'success':int(m.timely_evidence_complete),'delivered':int(m.brief_delivered),
                      'fresh':int(m.mandatory_sources_fresh),'calls':m.calls,'elapsed_s':round(m.elapsed_s,6)})
    write_csv(OUT/'heldout_workflow_trials.csv',rows)
    return rows,scenarios

def topology_eval(best):
    rows=[]
    for seed in range(140000,140120):
        for shape in ['chain','fanout','layered']:
            w=generate_workload(seed,n_tasks={'chain':8,'fanout':15,'layered':18}[shape])
            for sc in [Scenario('newgraph_iid',failure_prob=.23,deadline_s=50,mask_outages=True),
                       Scenario('newgraph_outage',failure_prob=.10,use_outages=True,deadline_s=55,mask_outages=True)]:
                cfg=dataclasses.replace(sc,adaptive_threshold=int(best['threshold']),
                      adaptive_short_s=best['short_s'],adaptive_long_s=best['long_s'])
                for pol in BASELINES:
                    m=simulate(w,cfg,pol)
                    rows.append({'split':'unseen_dag','seed':seed,'template':shape,'scenario':sc.name,
                          'policy':pol,'success':int(m.success),'delivered':int(m.success),
                          'fresh':int(m.success),'calls':m.calls,'elapsed_s':round(m.elapsed_s,6)})
    write_csv(OUT/'unseen_dag_trials.csv',rows)
    return rows

def report(rows):
    agg=collections.defaultdict(list)
    for r in rows:
        agg[(r['split'],r['template'],r['scenario'],r['policy'])].append(r)
    summary=[]
    for key,group in sorted(agg.items()):
        summary.append(dict(zip(('split','template','scenario','policy'),key),n=len(group),
             success_pct=round(mean(t['success'] for t in group)*100,2),
             mean_calls=round(mean(t['calls'] for t in group),3),
             mean_elapsed_s=round(mean(t['elapsed_s'] for t in group),3)))
    write_csv(OUT/'heldout_summary.csv',summary)
    paired=[]
    for (split,temp,scenario,policy),group in sorted(agg.items()):
        if policy!='history_adaptive':continue
        look={p:{x['seed']:x for x in agg[(split,temp,scenario,p)]} for p in BASELINES}
        seeds=sorted(look['history_adaptive'])
        for other in BASELINES:
            if other=='history_adaptive':continue
            differences=np.array([look['history_adaptive'][seed]['success']-look[other][seed]['success'] for seed in seeds],dtype=float)
            # deterministic paired nonparametric bootstrap; same seed contributes paired diff.
            rng=np.random.default_rng(2027+sum(map(ord,temp+scenario+other)))
            draws=rng.integers(0,len(differences),size=(2000,len(differences)))
            boots=differences[draws].mean(axis=1)*100
            paired.append({'split':split,'template':temp,'scenario':scenario,'compared_with':other,
                'n_paired':len(seeds),'difference_pp':round(100*differences.mean(),2),
                'ci_low':round(np.percentile(boots,2.5),2),'ci_high':round(np.percentile(boots,97.5),2)})
    write_csv(OUT/'heldout_paired_bootstrap.csv',paired)
    return summary,paired

if __name__=='__main__':
    best=develop()
    rows,cases=test(best);other=topology_eval(best)
    sumry,paired=report(rows+other)
    print('FROZEN',best)
    print('RECORDS',len(rows),len(other))
    for r in sumry:
        if r['template']=='information_environment_assessment': print('SUM',r['scenario'],r['policy'],r['success_pct'])
