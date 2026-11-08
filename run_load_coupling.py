"""Load-coupled outages (revision; Table V and Section V-D of the paper).

In the primary study, outage windows are scheduled in advance, so retries can never
prolong them. Here every request that reaches the service during an outage postpones
that outage's end by delta simulated seconds (Scenario.outage_load_delay_s), so the
policies that send more requests into an outage make it last longer. delta can also be
read as the effect of other clients that behave like this one. The model has no
fleet-level queueing, so it cannot produce a self-sustaining (metastable) outage.

Post hoc and exploratory: the frozen controller configuration is unchanged, and nothing
here is used to select a policy. delta = 0 reproduces the primary records exactly.

Outputs (results/load_coupling/):
  load_coupling_trials.csv / _summary.csv / _paired.csv
      Held-out outage scenario at the development outage length (+0 s) and the primary
      extended length (+2 s), held-out seeds 91000..91199, five policies.
  label_masking_under_load.csv
      The Table I label-masking control (seeds 2026..2225) rerun at each delta.

Run from the project root:  python run_load_coupling.py
"""
from __future__ import annotations
import collections, dataclasses, json
from pathlib import Path
from statistics import mean
import numpy as np
import run_diagnostics as diag
from retrybench.scenarios import MAIN_SCENARIOS
from retrybench.stratcom import TEMPLATES as WORKFLOWS, make_assessment_workload, simulate_assessment

ROOT = Path(__file__).parent
OUT = ROOT / 'results' / 'load_coupling'
DELTAS = (0., .1, .2, .3, .5, 1.)
LENGTHS = (0., 2.)  # outage-window extension: development length and the primary held-out test
POLICIES = diag.POLICIES
MASK_SEEDS = range(2026, 2226)
MASK_POLICIES = ('budget_aware', 'observable_cooldown', 'exponential', 'immediate')


def outage_runs():
    rows = []
    for ext in LENGTHS:
        for delta in DELTAS:
            cfg = dataclasses.replace(diag.OUTAGE, outage_load_delay_s=delta, **diag.TUNED)
            for template in diag.TEMPLATES:
                for seed in diag.TEST_SEEDS:
                    w = diag.workload_for(seed, template, diag.OUTAGE, ext)
                    for pol in POLICIES:
                        m, r = simulate_assessment(w, cfg, pol)
                        rows.append({'extension_s': ext, 'delta_s': delta, 'template': template, 'seed': seed,
                                     'policy': pol, 'success': int(m.timely_evidence_complete), 'calls': m.calls,
                                     'outage_requests': r.outage_errors,
                                     'outage_prolonged_s': round(delta * r.outage_errors, 6)})
    return rows


def summarise(rows):
    cell = collections.defaultdict(dict)
    extra = collections.defaultdict(list)
    for r in rows:
        cell[(r['extension_s'], r['delta_s'], r['template'], r['policy'])][r['seed']] = r['success']
        extra[(r['extension_s'], r['delta_s'], r['template'], r['policy'])].append((r['outage_requests'], r['outage_prolonged_s']))
    summary, paired = [], []
    for ext in LENGTHS:
        for delta in DELTAS:
            for template in diag.TEMPLATES + ['pooled']:
                temps = diag.TEMPLATES if template == 'pooled' else [template]
                for pol in POLICIES:
                    ys = [y for t in temps for y in cell[(ext, delta, t, pol)].values()]
                    ex = [x for t in temps for x in extra[(ext, delta, t, pol)]]
                    summary.append({'extension_s': ext, 'delta_s': delta, 'template': template, 'policy': pol, 'n': len(ys),
                                    'success_pct': round(100 * mean(ys), 2),
                                    'mean_outage_requests': round(mean(x[0] for x in ex), 3),
                                    'mean_outage_prolonged_s': round(mean(x[1] for x in ex), 3)})
                for other in ('exponential', 'observable_cooldown', 'immediate'):
                    diff = np.array([cell[(ext, delta, t, 'history_adaptive')][s] - cell[(ext, delta, t, other)][s]
                                     for t in temps for s in diag.TEST_SEEDS], dtype=float)
                    lo, hi = diag.paired_ci(diff, f'load{template}{other}{ext:g}{delta:g}')
                    paired.append({'extension_s': ext, 'delta_s': delta, 'template': template, 'compared_with': other,
                                   'n_paired': len(diff), 'difference_pp': round(100 * diff.mean(), 2), 'ci_low': lo, 'ci_high': hi})
    return summary, paired


def label_masking_under_load():
    base = {s.name: s for s in MAIN_SCENARIOS}['outage_45']
    rows = []
    for delta in DELTAS:
        for visible in (True, False):
            sc = dataclasses.replace(base, outage_load_delay_s=delta, mask_outages=not visible)
            for template in WORKFLOWS:
                for pol in MASK_POLICIES:
                    ys = [simulate_assessment(make_assessment_workload(seed, template), sc, pol)[0].timely_evidence_complete
                          for seed in MASK_SEEDS]
                    rows.append({'delta_s': delta, 'label': 'visible' if visible else 'masked', 'template': template,
                                 'policy': pol, 'n': len(ys), 'fresh_pct': round(100 * mean(ys), 2)})
    return rows


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    trials = outage_runs()
    diag.write_csv(OUT / 'load_coupling_trials.csv', trials)
    summary, paired = summarise(trials)
    diag.write_csv(OUT / 'load_coupling_summary.csv', summary)
    diag.write_csv(OUT / 'load_coupling_paired.csv', paired)
    masking = label_masking_under_load()
    diag.write_csv(OUT / 'label_masking_under_load.csv', masking)
    manifest = {
        'status': 'post-hoc exploratory; frozen configuration unchanged',
        'load_model': 'each request received during an outage postpones that outage window\'s end by delta_s simulated seconds',
        'deltas_s': list(DELTAS), 'outage_extensions_s': list(LENGTHS), 'seeds': '91000..91199',
        'trials': len(trials), 'label_masking_trials': sum(r['n'] for r in masking), 'label_masking_seeds': '2026..2225',
        'frozen_configuration': diag.FROZEN,
        'not_modelled': 'fleet-level queueing or self-sustaining overload; one workflow per trial',
    }
    (OUT / 'load_coupling_manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    for r in summary:
        if r['template'] == 'pooled':
            print(r['extension_s'], r['delta_s'], r['policy'], r['success_pct'], r['mean_outage_requests'], r['mean_outage_prolonged_s'])
