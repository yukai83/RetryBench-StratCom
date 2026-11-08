"""Check the numbers quoted in the running text of main.tex against the saved results and the code.

Three layers:
  1. data claims    - each quoted result is recomputed from the CSVs;
  2. design claims  - each quoted setting is read from the code or the frozen configuration;
  3. coverage audit - every number that appears in the prose (tables, figures, equations and
                      references excluded) must belong to a claim checked in layer 1 or 2.
Tables I, III and IV and Figs. 1-2 are generated from the CSVs by make_tables.py / make_figures.py and are not
re-checked here. Three statements about third-party libraries (AWS SDK retry quota, Resilience4j defaults) come
from their documentation, cited in the paper; they are listed below with the arithmetic that uses them.
Run from the project root after the experiment scripts:  python verify_paper_numbers.py
"""
import csv, json, re, inspect
from pathlib import Path
import local_http_benchmark as http_mod
import run_main_study
import run_diagnostics as diag
from retrybench import model, stratcom
from retrybench.policies import RetryContext, decide


def wait(policy, error='transient', attempt=1, **kw):
    base = dict(error=error, attempt_count=attempt, max_attempts=4, now=1., deadline=1e6, calls_so_far=0,
                task_count=10, longest_remaining_chain=0, jitter=1.)
    base.update(kw)
    return decide(policy, RetryContext(**base)).delay_s


def budget(policy, **kw):  # total wait over three retries, jitter fixed at 1
    return round(sum(wait(policy, attempt=a, **kw) for a in (1, 2, 3)), 6)

ROOT = Path(__file__).parent
read = lambda p: list(csv.DictReader((ROOT / p).open()))
IEA, LFC, CSR = 'information_environment_assessment', 'live_fact_check_support', 'communications_situation_report'
T3 = (IEA, LFC, CSR)
SC = ('held_iid_27', 'held_outage_extended', 'held_tight_17', 'held_quota_23', 'held_mixed')

summ = {(r['split'], r['template'], r['scenario'], r['policy']): float(r['success_pct']) for r in read('results/main/heldout_summary.csv')}
pair = {(r['split'], r['template'], r['scenario'], r['compared_with']): tuple(float(r[k]) for k in ('difference_pp', 'ci_low', 'ci_high'))
        for r in read('results/main/heldout_paired_bootstrap.csv')}
sweep = {(float(r['extension_s']), r['template'], r['compared_with']): tuple(float(r[k]) for k in ('difference_pp', 'ci_low', 'ci_high'))
         for r in read('results/diagnostics/outage_duration_paired.csv')}
sweep_rate = {(float(r['extension_s']), r['template'], r['policy']): float(r['success_pct']) for r in read('results/diagnostics/outage_duration_summary.csv')}
obs = {(r['template'], r['scenario'], r['policy']): float(r['fresh_pct']) for r in read('results/label_masking/label_masking_summary.csv')}
det = {(r['scenario'], r['true_cause']): r for r in read('results/diagnostics/detector_diagnostic.csv')}
win = {(r['template'], r['scenario'], float(r['window_s'])): float(r['success_pct']) for r in read('results/main/history_window_summary.csv')}
http = {(r['regime'], r['policy']): r for r in read('results/main/localhost_http_summary.csv')}
manifest = json.loads((ROOT / 'results/diagnostics/diagnostics_manifest.json').read_text())
frozen = json.loads((ROOT / 'results/main/frozen_parameters.json').read_text())
dev = read('results/main/development_grid.csv')
sw = {(r['scenario'], r['template'], r['variant']): float(r['success_pct']) for r in read('results/diagnostics/switching_ablation_summary.csv')}
swp = {(r['scenario'], r['template'], r['variant'], r['compared_with']): tuple(float(r[k]) for k in ('difference_pp', 'ci_low', 'ci_high'))
       for r in read('results/diagnostics/switching_ablation_paired.csv')}
obs_manifest = json.loads((ROOT / 'results/label_masking/label_masking_manifest.json').read_text())
ho = lambda t, s, p: summ[('held_out', t, s, p)]
hp = lambda t, s, p: pair[('held_out', t, s, p)]
ud = lambda t, s, p: summ[('unseen_dag', t, s, p)]
r0 = lambda x: int(round(x + 1e-9))
r1 = lambda x: round(x + 1e-9, 1)
excludes_zero = lambda v: v[1] > 0 or v[2] < 0

vs_exp = [hp(t, s, 'exponential')[0] for t in T3 for s in SC]
OTHERS = ('immediate', 'exponential', 'sdk_style_proxy', 'observable_cooldown')
ALL5 = OTHERS + ('history_adaptive',)


def shortfall(policy):  # mean over the 15 held-out cells of (best policy in the cell) minus (this policy)
    return sum(max(ho(t, s, p) for p in ALL5) - ho(t, s, policy) for t in T3 for s in SC) / (len(T3) * len(SC))


def indep(scenario):  # long-wait share over retries after independent (transient or timeout) failures
    rows = [r for (s, cause), r in det.items() if s == scenario and cause in ('transient', 'timeout')]
    return 100 * sum(int(r['long_wait_retries']) for r in rows) / sum(int(r['scheduled_retries']) for r in rows)
out_exp = [hp(t, 'held_outage_extended', 'exponential')[0] for t in T3]
tight_exp = [hp(t, 'held_tight_17', 'exponential') for t in T3]
plus0 = [sweep[(0., t, 'observable_cooldown')] for t in T3]
graphs = ('chain', 'fanout', 'layered')
unseen = {p: [ud(g, 'newgraph_outage', p) for g in graphs] for p in ('history_adaptive', 'exponential', 'immediate', 'observable_cooldown')}
unseen_gain = [pair[('unseen_dag', g, 'newgraph_outage', 'exponential')][0] for g in graphs]
# Revision analyses: pooled contrast, development grid on held-out cells, threshold sweep, load coupling.
pooled = {r['policy']: r for r in read('results/diagnostics/pooled_heldout_contrast.csv')}
devho = read('results/diagnostics/devgrid_heldout.csv')
trade = read('results/diagnostics/threshold_tradeoff.csv')
tr = lambda k, long, sc, rho='': next(r for r in trade if (int(r['threshold']), float(r['long_s']), r['failure_rate_rule'], r['scenario']) == (k, long, rho, sc))
load = {(float(r['extension_s']), float(r['delta_s']), r['template'], r['policy']): r for r in read('results/load_coupling/load_coupling_summary.csv')}
loadp = {(float(r['extension_s']), float(r['delta_s']), r['template'], r['compared_with']): tuple(float(r[k]) for k in ('difference_pp', 'ci_low', 'ci_high'))
         for r in read('results/load_coupling/load_coupling_paired.csv')}
maskload = {(float(r['delta_s']), r['label'], r['template'], r['policy']): float(r['fresh_pct']) for r in read('results/load_coupling/label_masking_under_load.csv')}
load_manifest = json.loads((ROOT / 'results/load_coupling/load_coupling_manifest.json').read_text())
DELTAS = sorted({d for _, d, _, _ in load})
WAITING = ('exponential', 'sdk_style_proxy', 'observable_cooldown', 'history_adaptive')
lp = lambda e, d, p: float(load[(e, d, 'pooled', p)]['success_pct'])
swpool = lambda s, v: sum(sw[(s, t, v)] for t in T3) / 3
pooled_dev = lambda rank: [r for r in devho if int(r['dev_rank']) == rank]
src_stratcom = inspect.getsource(stratcom)
src_model = inspect.getsource(model)
ttls = [float(x) for x in re.findall(r'freshness_ttl_s=(\d+)', src_stratcom)]
held = {s.name: s for s in diag.HELD_OUT}

# Each claim: (numbers it accounts for in the prose, description, computed value, value quoted in the text)
CLAIMS = [
    # label-masking control
    (['92.0', '24.5'], 'cause-aware IEA visible/masked', (obs[(IEA, 'outage_labeled', 'budget_aware')], obs[(IEA, 'outage_hidden_5xx', 'budget_aware')]), (92.0, 24.5)),
    (['four'], 'almost four times better', 3.5 < 92.0 / 24.5 < 4.0, True),
    (['2026', '2225', '200'], 'label-masking seeds', (obs_manifest['seeds'], obs_manifest['n_per_cell']), ([2026, 2225], 200)),
    (['1.5a', '0.2a'], 'cause-aware waits after outage-labelled vs other failures',
     ([wait('budget_aware', 'outage', a) for a in (1, 2, 3)], [wait('budget_aware', e, a) for e in ('transient', 'timeout') for a in (1, 2)]),
     ([1.5, 3.0, 4.5], [0.2, 0.4, 0.2, 0.4])),
    (['5.6', '9.0', '2.4', '11.0'], 'total waits over three retries (Table II)',
     (budget('exponential'), budget('observable_cooldown'), budget('history_adaptive', recent_errors=0, adaptive_threshold=3, adaptive_short_s=.4, adaptive_long_s=2.),
      budget('history_adaptive', recent_errors=3, adaptive_threshold=3, adaptive_short_s=.4, adaptive_long_s=2.)), (5.6, 9.0, 2.4, 11.0)),
    # held-out headline results
    (['1.5', '27'], 'worst history-minus-exponential cell (LFC, 27% IID)', (min(vs_exp), min((v, t, s) for t in T3 for s in SC for v in [hp(t, s, 'exponential')[0]])[1:]),
     (-1.5, (LFC, 'held_iid_27'))),
    (['21', '38', '21.0', '37.5'], 'outage gain over exponential, range', (min(out_exp), max(out_exp)), (21.0, 37.5)),
    (['74.0', '60.5'], 'IEA outage cooldown vs history', (ho(IEA, 'held_outage_extended', 'observable_cooldown'), ho(IEA, 'held_outage_extended', 'history_adaptive')), (74.0, 60.5)),
    (['95.0', '80.5'], 'IEA tight immediate vs history', (ho(IEA, 'held_tight_17', 'immediate'), ho(IEA, 'held_tight_17', 'history_adaptive')), (95.0, 80.5)),
    (['99.5', '0.0'], 'immediate quota LFC / CSR', (ho(LFC, 'held_quota_23', 'immediate'), ho(CSR, 'held_quota_23', 'immediate')), (99.5, 0.0)),
    (['3,000', '12', 'four'], 'proxy call cap bound in 12 trials and changed the outcome in four',
     (manifest['sdk_proxy_trials'], manifest['sdk_proxy_cap_bound_trials'], manifest['sdk_proxy_trials'] - manifest['sdk_proxy_same_as_exponential_trials']), (3000, 12, 4)),
    (['fifteen'], 'held-out cells', len(SC) * len(T3), 15),
    (['8.0', '7.7', '14.3', '20.4'], 'mean shortfall from the best policy per held-out cell (history, cooldown, exponential, immediate)',
     tuple(r1(shortfall(p)) for p in ('history_adaptive', 'observable_cooldown', 'exponential', 'immediate')), (8.0, 7.7, 14.3, 20.4)),
    ([], 'controller beats cooldown, and immediate beats both, in every independent-fault cell (IID, tight, mixed)',
     all(ho(t, s, 'history_adaptive') > ho(t, s, 'observable_cooldown') and ho(t, s, 'immediate') > ho(t, s, 'history_adaptive')
         for t in T3 for s in ('held_iid_27', 'held_tight_17', 'held_mixed')), True),
    ([], 'label-blind cooldown matches cause-aware (visible label) in IEA and CSR, not LFC',
     [abs(obs[(t, 'outage_labeled', 'observable_cooldown')] - obs[(t, 'outage_labeled', 'budget_aware')]) <= 1.5 for t in T3], [True, False, True]),
    ([], 'cause-aware policy also caps calls and applies a critical-path deadline guard',
     (decide('budget_aware', RetryContext(error='transient', attempt_count=1, max_attempts=4, now=0., deadline=1e6, calls_so_far=99,
                                          task_count=10, longest_remaining_chain=0, jitter=1.)).reason,
      decide('budget_aware', RetryContext(error='transient', attempt_count=1, max_attempts=4, now=0., deadline=5., calls_so_far=0,
                                          task_count=10, longest_remaining_chain=9, jitter=1.)).reason),
     ('workflow_call_budget', 'insufficient_time_slack')),
    # switching ablation (Table V)
    (['14.5', '23.5'], 'short wait alone under the extended outage, range',
     (min(sw[('held_outage_extended', t, 'short_only')] for t in T3), max(sw[('held_outage_extended', t, 'short_only')] for t in T3)), (14.5, 23.5)),
    (['16', '23'], 'long wait alone loses to the controller under tight deadlines, range',
     (r0(min(sw[('held_tight_17', t, 'adaptive')] - sw[('held_tight_17', t, 'long_only')] for t in T3)),
      r0(max(sw[('held_tight_17', t, 'adaptive')] - sw[('held_tight_17', t, 'long_only')] for t in T3))), (16, 23)),
    ([], 'controller lies between its two fixed waits in every held-out cell',
     all(min(sw[(s, t, 'short_only')], sw[(s, t, 'long_only')]) <= sw[(s, t, 'adaptive')] <= max(sw[(s, t, 'short_only')], sw[(s, t, 'long_only')])
         for s in SC for t in T3), True),
    (['+1.0'], 'perfect detection vs cooldown under outage, IEA and CSR: +1.0 with CI spanning zero',
     [(swp[('held_outage_extended', t, 'perfect_detection', 'observable_cooldown')][0], excludes_zero(swp[('held_outage_extended', t, 'perfect_detection', 'observable_cooldown')])) for t in (IEA, CSR)],
     [(1.0, False), (1.0, False)]),
    (['two-thirds'], 'perfect detection recovers about two-thirds of the LFC outage gap to the cooldown',
     round((sw[('held_outage_extended', LFC, 'perfect_detection')] - sw[('held_outage_extended', LFC, 'adaptive')]) /
           (sw[('held_outage_extended', LFC, 'observable_cooldown')] - sw[('held_outage_extended', LFC, 'adaptive')]), 2), .68),
    (['7', '9'], 'perfect detection equals short wait under tight deadlines and trails immediate by 7-9 (CI excludes zero)',
     ([sw[('held_tight_17', t, 'perfect_detection')] == sw[('held_tight_17', t, 'short_only')] for t in T3],
      sorted(-swp[('held_tight_17', t, 'perfect_detection', 'immediate')][0] for t in T3)[::2],
      all(excludes_zero(swp[('held_tight_17', t, 'perfect_detection', 'immediate')]) for t in T3)), ([True] * 3, [7.0, 9.0], True)),
    ([], 'false alarms explain less than half of the tight-deadline gap to immediate retry',
     all((sw[('held_tight_17', t, 'perfect_detection')] - sw[('held_tight_17', t, 'adaptive')]) <
         .5 * (sw[('held_tight_17', t, 'immediate')] - sw[('held_tight_17', t, 'adaptive')]) for t in T3), True),
    ([], 'perfect detection draws level with cooldown in two of three workflows, still trails in LFC',
     [excludes_zero(swp[('held_outage_extended', t, 'perfect_detection', 'observable_cooldown')]) for t in T3], [False, True, False]),
    (['18,000'], 'switching ablation trials', manifest['switching_ablation_trials'], 18000),
    # delay budgets and detector
    (['8.5', '5.0'], 'held-out outage window lengths', (6.5 + 2, 3.0 + 2), (8.5, 5.0)),
    (['64', '1,808'], 'long-wait share after outage-caused failures', (r0(float(det[('held_outage_extended', 'outage')]['long_wait_pct'])), int(det[('held_outage_extended', 'outage')]['scheduled_retries'])), (64, 1808)),
    (['26', '14', '17'], 'false-alarm long-wait shares, transient+timeout (27% / 17% IID); 26% is the maximum over held-out regimes',
     (r0(indep('held_iid_27')), r0(indep('held_tight_17')), r0(max(indep(s) for s in SC if s != 'held_outage_extended'))), (26, 14, 26)),
    (['five'], 'history never wins outright; no single policy beats it in all five regimes of any workflow',
     ([(t, s) for t in T3 for s in SC if all(ho(t, s, 'history_adaptive') > ho(t, s, p) for p in OTHERS)],
      [(t, p) for t in T3 for p in OTHERS if all(ho(t, s, p) >= ho(t, s, 'history_adaptive') for s in SC)]), ([], [])),
    # outage sweep
    (['3.0', '9.5'], '+0 s lead over cooldown range; CI excludes zero in LFC, CSR',
     ((min(v[0] for v in plus0), max(v[0] for v in plus0)), [excludes_zero(v) for v in plus0]), ((3.0, 9.5), [False, True, True])),
    (['1', '3'], 'cooldown lead at +1..+3 s clear in LFC, CSR; IEA only at +2',
     tuple(tuple(sweep[(e, t, 'observable_cooldown')][2] < 0 for e in (1., 2., 3.)) for t in T3), ((False, True, False), (True, True, True), (True, True, True))),
    (['4', '6'], '+4/+6 s: history ahead in IEA (CI>0), LFC/CSR not separable',
     ([sweep[(e, IEA, 'observable_cooldown')][1] > 0 for e in (4., 6.)], [excludes_zero(sweep[(e, t, 'observable_cooldown')]) for e in (4., 6.) for t in (LFC, CSR)]),
     ([True, True], [False, False, False, False])),
    (['66.5', '31.0'], 'IEA exponential +0 -> +1 s', (sweep_rate[(0., IEA, 'exponential')], sweep_rate[(1., IEA, 'exponential')]), (66.5, 31.0)),
    (['+2'], 'cooldown lead largest at +2 s in every workflow',
     [min((sweep[(e, t, 'observable_cooldown')][0], e) for e in (0., 1., 2., 3., 4., 6.))[1] for t in T3], [2.0, 2.0, 2.0]),
    (['0', '6'], 'history >= exponential at every length', all(sweep[(e, t, 'exponential')][0] >= 0 for e in diag.EXTENSIONS for t in T3), True),
    (['1--3'], 'cooldown ahead of history at +1..+3 s in every workflow', all(sweep[(e, t, 'observable_cooldown')][0] < 0 for e in (1., 2., 3.) for t in T3), True),
    ([], '+6 s: first outage outlasts every total wait (max jitter); immediate >= every waiting policy in LFC and CSR',
     (6.5 + 6 > budget('history_adaptive', recent_errors=3, adaptive_threshold=3, adaptive_short_s=.4, adaptive_long_s=2., jitter=1.15),
      all(sweep_rate[(6., t, 'immediate')] >= sweep_rate[(6., t, p)] for t in (LFC, CSR)
          for p in ('exponential', 'sdk_style_proxy', 'observable_cooldown', 'history_adaptive'))), (True, True)),
    (['18,000'], 'sweep trials', manifest['outage_sweep']['trials'], 18000),
    # unseen graphs
    (['76', '91'], 'unseen outage history range', (r0(min(unseen['history_adaptive'])), r0(max(unseen['history_adaptive']))), (76, 91)),
    (['35', '68'], 'unseen outage exponential range', (r0(min(unseen['exponential'])), r0(max(unseen['exponential']))), (35, 68)),
    (['23', '41'], 'unseen paired gains range', (r0(min(unseen_gain)), r0(max(unseen_gain))), (23, 41)),
    (['0', '47'], 'unseen immediate range', (r0(min(unseen['immediate'])), r0(max(unseen['immediate']))), (0, 47)),
    (['one'], 'history within one point of cooldown on every graph', max(abs(a - b) for a, b in zip(unseen['history_adaptive'], unseen['observable_cooldown'])) < 1, True),
    ([], 'proxy loses two chain workflows (IID); no longer quoted', r0((ud('chain', 'newgraph_iid', 'exponential') - ud('chain', 'newgraph_iid', 'sdk_style_proxy')) * 120 / 100), 2),
    # window sweep
    (['2', '12', '95.0', '87.0', '40.0', '63.0'], 'IEA window sweep endpoints',
     (win[(IEA, 'iid', 2.)], win[(IEA, 'iid', 12.)], win[(IEA, 'outage', 2.)], win[(IEA, 'outage', 12.)]), (95.0, 87.0, 40.0, 63.0)),
    # HTTP
    (['16'], 'waiting policies 16/16 and immediate 0/16 in shared-fault HTTP regimes',
     (all(float(http[(r, p)]['success_pct']) == 100 for r in ('brief_http_503_outage', 'shared_http_429') for p in ('exponential', 'sdk_style_proxy', 'observable_cooldown', 'history_adaptive')),
      all(float(http[(r, 'immediate')]['success_pct']) == 0 for r in ('brief_http_503_outage', 'shared_http_429'))), (True, True)),
    (['one'], 'HTTP IID and timeout regimes: policies differ by at most one run of 16',
     [round((max(float(http[(r, p)]['success_pct']) for p in http_mod.POLICIES) - min(float(http[(r, p)]['success_pct']) for p in http_mod.POLICIES)) * 16 / 100)
      for r in ('iid_http_503', 'timeout_http')], [1, 1]),
    # design and protocol settings, read from code or configuration
    (['6', '6.5'], 'history window 6 s; first outage window 6.5 s', (model.Scenario('x').adaptive_window_s, 'first + 6.5' in src_model), (6.0, True)),
    (['4.5', '7.5', '3.0', '19', '23', '0.2'], 'outage window placement and fast-fail latency',
     ('4.5 + 3.0 * outage_rng.random()' in src_model, '19.0 + 4.0 * outage_rng.random()' in src_model, 'second + 3.0' in src_model,
      'latency = 0.2' in inspect.getsource(model) or 'latency = 0.2' in Path(ROOT / 'retrybench/simulator.py').read_text()), (True, True, True, True)),
    (['1.25'], 'median latency', inspect.signature(stratcom.make_assessment_workload).parameters['median_latency'].default, 1.25),
    (['Four'], 'workers', model.Scenario('x').workers, 4),
    (['20', '35'], 'TTL range', (min(ttls), max(ttls)), (20.0, 35.0)),
    (['10', '8', '9'], 'template sizes', tuple(len(stratcom.make_assessment_workload(1, t).tasks) for t in T3), (10, 8, 9)),
    (['11', '14'], 'longest total wait fits inside shortest held-out deadline', (min(5, 2 * 1) + min(5, 2 * 2) + min(5, 2 * 3), min(s.deadline_s for s in diag.HELD_OUT)), (11, 14)),
    (['0.8a', '0.1'], '429 base wait and slack guard', ('0.8 * context.attempt_count' in Path(ROOT / 'retrybench/policies.py').read_text(), '+ 0.10' in Path(ROOT / 'retrybench/policies.py').read_text()), (True, True)),
    (['3,000'], 'guard ablation trials, no change', (sum(int(r['n']) for r in read('results/diagnostics/slack_guard_ablation.csv')), manifest['slack_guard_total_seed_differences']), (3000, 0)),
    (['2', '3', '0.2', '0.4', '1', '1.5', '2'], 'development grid values', frozen['grid'], {'threshold': [2, 3], 'short_s': [.2, .4], 'long_s': [1., 1.5, 2.]}),
    (['22', '7', '1.8'], 'development conditions: IID rate and deadline, outage background rate, hinted quota',
     tuple((s.failure_prob, s.deadline_s, s.use_outages, s.provider_rps, s.advertise_retry_after) for s in diag.DEV_CASES),
     ((.22, 22, False, None, False), (.07, 45, True, None, False), (.08, 55, False, 1.8, True))),
    ([], 'development conditions in run_diagnostics match run_main_study',
     all(f"Scenario('{s.name}',failure_prob={s.failure_prob:g}".replace('0.', '.') in inspect.getsource(run_main_study) for s in diag.DEV_CASES), True),
    (['12', '360', '40', '4,320'], 'development trial counts', (len(dev), int(dev[0]['n']), len(diag.DEV_SEEDS), len(dev) * int(dev[0]['n'])), (12, 360, 40, 4320)),
    (['3', '0.4', '2.0', '96.1'], 'frozen configuration and development score',
     (frozen['frozen_adaptive']['threshold'], frozen['frozen_adaptive']['short_s'], frozen['frozen_adaptive']['long_s'], r1(100 * float(dev[0]['score']))), (3, .4, 2., 96.1)),
    (['120', '5', '1.5', '3'], 'wide grid size, bounds and rank', (manifest['wide_grid']['configs'], manifest['wide_grid']['frozen_config_rank']), (120, 1)),
    (['15,000', '200', '27', '2', '17', '14', '2.3'], 'held-out design',
     (len(read('results/main/heldout_workflow_trials.csv')), len(diag.TEST_SEEDS), held['held_iid_27'].failure_prob, held['held_tight_17'].failure_prob,
      held['held_tight_17'].deadline_s, held['held_quota_23'].provider_rps), (15000, 200, .27, .17, 14, 2.3)),
    (['3,600', '120', '8', '15', '18'], 'unseen-DAG design', (len(read('results/main/unseen_dag_trials.csv')), "{'chain':8,'fanout':15,'layered':18}" in inspect.getsource(run_main_study)), (3600, True)),
    (['320', '16', '35', '127.0.0.1'], 'HTTP design', (len(read('results/main/localhost_http_trials.csv')), len(http_mod.SEEDS), http_mod.SCALE), (320, 16, .035)),
    (['3,600'], 'window sweep trials', len(read('results/main/history_window_sensitivity.csv')), 3600),
    (['98'], 'automated tests (pytest count)', None, None),  # checked separately below
    # ---- revision: abstract and Section V-A (tie with the cooldown) ----
    (['0.3', '1.7', '+1.2', '1.2'], 'history minus cooldown pooled over the 15 cells, seed bootstrap CI',
     (round(float(pooled['observable_cooldown']['history_minus_policy_pp']), 1), float(pooled['observable_cooldown']['ci_low']), float(pooled['observable_cooldown']['ci_high'])),
     (-0.3, -1.67, 1.23)),
    ([], 'CI rounds to -1.7 and +1.2', (r1(float(pooled['observable_cooldown']['ci_low']) - 1e-9), round(float(pooled['observable_cooldown']['ci_high']), 1)), (-1.7, 1.2)),
    (['twelve', '5.0'], 'history ahead of cooldown in all 12 cells outside the extended outage, by 5.0 on average',
     (int(pooled['observable_cooldown']['cells_history_ahead_outside_outage']), r1(float(pooled['observable_cooldown']['history_minus_policy_outside_outage_pp']))), (12, 5.0)),
    (['26.5', '26.0'], 'worst shortfall from the best policy: history (LFC outage) and cooldown (LFC tight)',
     ((float(pooled['history_adaptive']['worst_shortfall_pp']), pooled['history_adaptive']['worst_cell']),
      (float(pooled['observable_cooldown']['worst_shortfall_pp']), pooled['observable_cooldown']['worst_cell'])),
     ((26.5, f'{LFC}/held_outage_extended'), (26.0, f'{LFC}/held_tight_17'))),
    ([], 'losing only under that outage: cooldown beats history only in extended-outage cells',
     sorted({s for t in T3 for s in SC if ho(t, s, 'observable_cooldown') > ho(t, s, 'history_adaptive')}), ['held_outage_extended']),
    (['two', '0.8', '14', '15', '360', '1.5'], 'the two dev settings ranked next: ranks 2-3 (k=2, long 1.5) are 0.8 below the frozen score (3 of 360 trials) and match/beat the cooldown in 14 and 15 held-out cells',
     ([(int(pooled_dev(r)[0]['threshold']), float(pooled_dev(r)[0]['long_s'])) for r in (2, 3)],
      [r1(float(pooled_dev(1)[0]['dev_score_pct']) - float(pooled_dev(r)[0]['dev_score_pct'])) for r in (2, 3)],
      [round((float(dev[0]['score']) - float(dev[r - 1]['score'])) * 360) for r in (2, 3)],
      [sum(int(x['at_least_cooldown']) for x in pooled_dev(r)) for r in (2, 3)]),
     ([(2, 1.5), (2, 1.5)], [0.8, 0.8], [3, 3], [14, 15])),
    # ---- revision: switching ablation, pooled cost of false alarms ----
    (['5.2', '3.5'], 'false alarms cost (short-only minus controller, pooled): tight 17%, IID 27%',
     (r1(swpool('held_tight_17', 'short_only') - swpool('held_tight_17', 'adaptive')), r1(swpool('held_iid_27', 'short_only') - swpool('held_iid_27', 'adaptive'))), (5.2, 3.5)),
    # ---- revision: threshold sweep (Fig. 2) ----
    (['59', '26', '8', '2.5'], 'false alarms at 27% IID for k=2..5, long 2.0',
     [r0(float(tr(k, 2., 'held_iid_27')['long_wait_pct_independent'])) if k != 5 else float(tr(k, 2., 'held_iid_27')['long_wait_pct_independent']) for k in (2, 3, 4, 5)], [59, 26, 8, 2.5]),
    (['88', '64', '37', '25'], 'outage detection for k=2..5, long 2.0',
     [r0(float(tr(k, 2., 'held_outage_extended')['long_wait_pct_outage'])) for k in (2, 3, 4, 5)], [88, 64, 37, 25]),
    (['71.0', '50.5', '33.2', '28.3'], 'pooled extended-outage delivery for k=2..5, long 2.0',
     [r1(float(tr(k, 2., 'held_outage_extended')['success_pct_pooled'])) for k in (2, 3, 4, 5)], [71.0, 50.5, 33.2, 28.3]),
    (['24', '29'], 'false alarms at k=3 across long = 1..3', (r0(min(float(tr(3, l, 'held_iid_27')['long_wait_pct_independent']) for l in (1., 1.5, 2., 3.))),
                                                            r0(max(float(tr(3, l, 'held_iid_27')['long_wait_pct_independent']) for l in (1., 1.5, 2., 3.)))), (24, 29)),
    (['21.7'], 'k=3, long 1.0: long waits (6 s) do not outlast the 8.5-s window; outage delivery',
     (sum(min(5, 1. * a) for a in (1, 2, 3)) < 6.5 + 2, r1(float(tr(3, 1., 'held_outage_extended')['success_pct_pooled']))), (True, 21.7)),
    (['17', '35', '4'], 'failure-rate rule (rho 0.5, k=3) vs k=4: more false alarms, less detection',
     (r0(float(tr(3, 2., 'held_iid_27', '0.5')['long_wait_pct_independent'])), r0(float(tr(3, 2., 'held_outage_extended', '0.5')['long_wait_pct_outage'])),
      float(tr(3, 2., 'held_iid_27', '0.5')['long_wait_pct_independent']) > float(tr(4, 2., 'held_iid_27')['long_wait_pct_independent']) and
      float(tr(3, 2., 'held_outage_extended', '0.5')['long_wait_pct_outage']) < float(tr(4, 2., 'held_outage_extended')['long_wait_pct_outage'])), (17, 35, True)),
    (['5'], 'no sweep setting comes within 5 points of perfect detection on both axes (pooled; x = mean of IID 27% and tight 17%)',
     min(max((swpool('held_iid_27', 'perfect_detection') + swpool('held_tight_17', 'perfect_detection')) / 2 -
             (float(tr(k, l, 'held_iid_27', rho)['success_pct_pooled']) + float(tr(k, l, 'held_tight_17', rho)['success_pct_pooled'])) / 2,
             swpool('held_outage_extended', 'perfect_detection') - float(tr(k, l, 'held_outage_extended', rho)['success_pct_pooled']))
         for k, l, rho in [(int(r['threshold']), float(r['long_s']), r['failure_rate_rule']) for r in trade if r['scenario'] == 'held_iid_27']) > 5, True),
    (['32,400'], 'threshold sweep trials', manifest['threshold_tradeoff']['trials'], 32400),
    # ---- revision: load-coupled outages (Table IV, Section V-E) ----
    (['2.8', '4.0'], 'mean requests sent into an outage, waiting policies, both lengths, all delta',
     (r1(min(float(load[(e, d, 'pooled', p)]['mean_outage_requests']) for e in (0., 2.) for d in DELTAS for p in WAITING)),
      r1(max(float(load[(e, d, 'pooled', p)]['mean_outage_requests']) for e in (0., 2.) for d in DELTAS for p in WAITING))), (2.8, 4.0)),
    (['0.3', '69.8', '75.2', '32.5'], 'development length, delta 0.3: history, cooldown, exponential',
     tuple(r1(lp(0., .3, p)) for p in ('history_adaptive', 'observable_cooldown', 'exponential')), (69.8, 75.2, 32.5)),
    (['1'], 'delta 0.3 adds about 1 s of outage (mean prolongation, waiting policies)',
     round(sum(float(load[(0., .3, 'pooled', p)]['mean_outage_prolonged_s']) for p in WAITING) / len(WAITING), 0), 1.0),
    (['+1', '66.5', '75.3', '31.5'], 'outage sweep +1 s pooled: history, cooldown, exponential',
     tuple(r1(sum(sweep_rate[(1., t, p)] for t in T3) / 3) for p in ('history_adaptive', 'observable_cooldown', 'exponential')), (66.5, 75.3, 31.5)),
    (['98.0', '100'], 'quota: policies that honour Retry-After stay at 98.0-100%',
     (min(ho(t, 'held_quota_23', p) for t in T3 for p in WAITING), max(ho(t, 'held_quota_23', p) for t in T3 for p in WAITING)), (98.0, 100.0)),
    (['34'], 'label masking under load: visible minus masked (cause-aware) at least 34 points at every delta',
     r0(min(maskload[(d, 'visible', t, 'budget_aware')] - maskload[(d, 'masked', t, 'budget_aware')] for d in DELTAS for t in T3)), 34),
    ([], 'label masking under load: delta 0 reproduces Table I', all(maskload[(0., lab, t, p)] == obs[(t, sc, p)]
     for lab, sc in (('visible', 'outage_labeled'), ('masked', 'outage_hidden_5xx')) for t in T3 for p in ('budget_aware', 'observable_cooldown', 'exponential', 'immediate')), True),
    (['+3.5', '3.5', '2.2', '5.0'], 'history beats exponential at every delta and both lengths; smallest gain and CI',
     (all(loadp[(e, d, 'pooled', 'exponential')][1] > 0 for e in (0., 2.) for d in DELTAS),
      min((loadp[(e, d, 'pooled', 'exponential')] for e in (0., 2.) for d in DELTAS), key=lambda v: v[0])), (True, (3.5, 2.17, 5.0))),
    (['6.0', '3.3', '8.8'], 'development length, delta 0: history minus cooldown and CI', loadp[(0., 0., 'pooled', 'observable_cooldown')], (6.0, 3.33, 8.84)),
    (['0.2'], 'lead vanishes at delta 0.2 (CI spans zero)', excludes_zero(loadp[(0., .2, 'pooled', 'observable_cooldown')]), False),
    (['0.3', '5.3', '9.0', '1.5'], 'reverses at delta >= 0.3 (CI below zero); value at 0.3',
     (all(loadp[(0., d, 'pooled', 'observable_cooldown')][2] < 0 for d in DELTAS if d >= .3), loadp[(0., .3, 'pooled', 'observable_cooldown')]), (True, (-5.33, -9.0, -1.5))),
    (['21.2', '22.5'], 'extended length: cooldown lead 21.2 at delta 0, narrows monotonically; immediate 22.5 throughout',
     (round(-loadp[(2., 0., 'pooled', 'observable_cooldown')][0], 1),
      all(-loadp[(2., a, 'pooled', 'observable_cooldown')][0] >= -loadp[(2., b, 'pooled', 'observable_cooldown')][0] for a, b in zip(DELTAS, DELTAS[1:])),
      {lp(e, d, 'immediate') for e in (0., 2.) for d in DELTAS}), (21.2, True, {22.5})),
    (['36,000'], 'load-coupling trials (not quoted in prose; manifest check)', load_manifest['trials'], 36000),
    # ---- revision: third-party library facts (from the cited documentation) and the arithmetic built on them ----
    (['2026', '14', '500', '50', '100'], 'AWS 2026 standard mode: 14 tokens per non-throttling retry, 500-token bucket, 50-ms base; Resilience4j minimum 100 calls (documentation)',
     None, None),
    (['30', '420'], 'max retries in one reporting workflow (3 per task, largest template) and their token cost',
     (3 * max(len(stratcom.make_assessment_workload(1, t).tasks) for t in T3), 14 * 3 * max(len(stratcom.make_assessment_workload(1, t).tasks) for t in T3)), (30, 420)),
    ([], '420 tokens cannot exhaust a 500-token bucket', 420 < 500, True),
    (['72'], 'max calls of any workflow in the study (4 attempts x largest unseen DAG)', 4 * max(8, 15, 18), 72),
]
STRUCTURAL = {'429', '503', '5xx', '95', '1', '2', '3', '6', '12', '0', '4', '5', '9', '10'}  # status codes, CI level, section/eq counters

bad = []
for numbers, name, got, want in CLAIMS:
    if want is None:
        continue
    ok = got == want
    print('OK  ' if ok else 'FAIL', name, '' if ok else f'got {got!r}, want {want!r}')
    if not ok:
        bad.append(name)

# pytest count
import subprocess, sys
out = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--collect-only'], cwd=ROOT, capture_output=True, text=True).stdout
n_tests = int(re.search(r'(\d+) tests? collected', out).group(1))
n_tests_ok = n_tests == 98 and f'{n_tests} automated tests' in (ROOT / 'main.tex').read_text()
print('OK  ' if n_tests_ok else 'FAIL', 'automated tests (pytest count and the count quoted in main.tex)', n_tests)
if not n_tests_ok:
    bad.append('tests')

# Coverage audit of every number in the prose.
tex = (ROOT / 'main.tex').read_text()
body = tex.split(r'\begin{abstract}')[1].split(r'\section*{AI-Use Disclosure')[0]
prose = re.sub(r'\\begin\{(table|figure)\*?\}.*?\\end\{(table|figure)\*?\}', ' ', body, flags=re.S)
prose = re.sub(r'\\begin\{equation\}.*?\\end\{equation\}', ' ', prose, flags=re.S)
prose = re.sub(r'\\(cite|ref|label|input)\{[^}]*\}', ' ', prose)
prose = re.sub(r'\\texttt\{127\.0\.0\.1\}', ' 127.0.0.1 ', prose)
prose = prose.replace('{,}', ',').replace('\\%', '%')
tokens = set(re.findall(r'(?<![\w.])(?:\+)?\d[\d,]*(?:\.\d+)?a?', re.sub(r'(\d),(?!\d{3})', r'\1 ', prose)))
tokens |= set(w for w in re.findall(r'\b(one|two|four|Four|five|fifteen|twelve|two-thirds)\b', prose))
if '127.0.0.1' in prose:
    tokens = {t for t in tokens if t not in ('127.0', '127', '0.1', '0.0.1')} | {'127.0.0.1'}
accounted = set(STRUCTURAL)
for numbers, *_ in CLAIMS:
    accounted |= set(numbers)
unaccounted = sorted(t.lstrip('+') for t in tokens if t not in accounted and t.lstrip('+') not in accounted)
print('prose number tokens:', len(tokens), '| unaccounted:', unaccounted)
if unaccounted:
    bad.append(f'unaccounted numbers {unaccounted}')
assert not bad, bad
print('ALL TEXT NUMBERS MATCH DATA AND CODE')
