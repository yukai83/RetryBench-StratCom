"""Read-back reconciliation of every saved result used in the paper. Writes results/audit.json.

Run from the project root after the experiment scripts.
"""
import csv, json, math, collections
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).parent
MASK, MAIN, DIAG = ROOT / 'results/label_masking', ROOT / 'results/main', ROOT / 'results/diagnostics'
read = lambda p: list(csv.DictReader(p.open()))
checks = {}

# A. Label-masking control (Table I).
lm = read(MASK / 'label_masking_trials.csv')
key = {(r['template'], r['scenario'], r['policy'], r['seed']): r for r in lm}
checks['label_masking_count'] = len(lm) == 15000
checks['label_masking_unique_keys'] = len(key) == len(lm)
same = lambda a, b: (a['fresh'], a['delivered'], a['calls'], a['elapsed_s']) == (b['fresh'], b['delivered'], b['calls'], b['elapsed_s'])
checks['label_blind_policies_identical_visible_vs_masked'] = all(
    same(r, key[(t, 'outage_hidden_5xx', p, s)]) for (t, sc, p, s), r in key.items()
    if sc == 'outage_labeled' and p in ('immediate', 'exponential', 'observable_cooldown'))
cells = collections.defaultdict(list)
for r in lm:
    cells[(r['template'], r['scenario'], r['policy'])].append(int(r['fresh']))
checks['label_masking_summary_recomputed'] = all(
    math.isclose(100 * mean(cells[(r['template'], r['scenario'], r['policy'])]), float(r['fresh_pct']), abs_tol=.01)
    for r in read(MASK / 'label_masking_summary.csv'))

# B. Main study: development grid, held-out, unseen graphs, window sweep and localhost HTTP.
held, unseen = read(MAIN / 'heldout_workflow_trials.csv'), read(MAIN / 'unseen_dag_trials.csv')
http, window = read(MAIN / 'localhost_http_trials.csv'), read(MAIN / 'history_window_sensitivity.csv')
checks['heldout_count'] = len(held) == 15000
checks['unseen_dag_count'] = len(unseen) == 3600
checks['http_count'] = len(http) == 320
checks['history_window_count'] = len(window) == 3600
for name, rows, expected in [('heldout', held, 200), ('unseen', unseen, 120), ('http', http, 16), ('window', window, 200)]:
    seen = collections.defaultdict(set)
    for r in rows:
        dims = (r.get('template'), r.get('scenario', r.get('regime')), r.get('policy', r.get('window_s')))
        assert r['seed'] not in seen[dims], f'duplicate trial {name} {dims} {r["seed"]}'
        seen[dims].add(r['seed'])
    checks[f'{name}_cell_sizes'] = all(len(s) == expected for s in seen.values())
summary = {(r['split'], r['template'], r['scenario'], r['policy']): float(r['success_pct']) for r in read(MAIN / 'heldout_summary.csv')}
groups = collections.defaultdict(list)
for r in held + unseen:
    groups[(r['split'], r['template'], r['scenario'], r['policy'])].append(int(r['success']))
checks['main_summary_recomputed'] = set(groups) == set(summary) and all(
    math.isclose(100 * mean(v), summary[k], abs_tol=.01) for k, v in groups.items())
frozen = json.loads((MAIN / 'frozen_parameters.json').read_text())['frozen_adaptive']
dev = read(MAIN / 'development_grid.csv')
checks['frozen_config_is_top_of_development_grid'] = (
    len(dev) == 12 and (int(dev[0]['threshold']), float(dev[0]['short_s']), float(dev[0]['long_s'])) ==
    (frozen['threshold'], frozen['short_s'], frozen['long_s']))
seed_sets = {'masking': {int(r['seed']) for r in lm}, 'dev': set(range(61100, 61140)), 'heldout': {int(r['seed']) for r in held},
             'unseen': {int(r['seed']) for r in unseen}, 'http': {int(r['seed']) for r in http}}
names = list(seed_sets)
checks['seed_ranges_disjoint'] = all(not (seed_sets[a] & seed_sets[b]) for i, a in enumerate(names) for b in names[i + 1:])

# C. Post-hoc diagnostics.
sweep = read(DIAG / 'outage_duration_trials.csv')
held_outage = {(r['template'], r['policy'], r['seed']): r['success'] for r in held if r['scenario'] == 'held_outage_extended'}
two = [r for r in sweep if float(r['extension_s']) == 2.]
checks['sweep_trial_count'] = len(sweep) == 6 * 3 * 200 * 5
checks['sweep_plus2_matches_heldout_seed_for_seed'] = len(two) == len(held_outage) and all(
    held_outage[(r['template'], r['policy'], r['seed'])] == r['success'] for r in two)
cell = collections.defaultdict(list)
for r in sweep:
    cell[(r['extension_s'], r['template'], r['policy'])].append(int(r['success']))
checks['sweep_summary_recomputed'] = all(
    math.isclose(100 * mean(cell[(r['extension_s'], r['template'], r['policy'])]), float(r['success_pct']), abs_tol=.01)
    for r in read(DIAG / 'outage_duration_summary.csv'))
primary = {(r['template'], r['compared_with']): r for r in read(MAIN / 'heldout_paired_bootstrap.csv')
           if r['scenario'] == 'held_outage_extended'}
checks['sweep_plus2_ci_matches_primary'] = all(
    (r['difference_pp'], r['ci_low'], r['ci_high']) == tuple(primary[(r['template'], r['compared_with'])][k] for k in ('difference_pp', 'ci_low', 'ci_high'))
    for r in read(DIAG / 'outage_duration_paired.csv') if float(r['extension_s']) == 2.)
tuning = {(int(r['threshold']), float(r['short_s']), float(r['long_s'])): float(r['score']) for r in dev}
wide = read(DIAG / 'wide_development_grid.csv')
checks['wide_grid_size'] = len(wide) == 120
checks['wide_grid_contains_tuning_grid_scores'] = sum(r['in_tuning_grid'] == '1' for r in wide) == 12 and all(
    math.isclose(tuning[(int(r['threshold']), float(r['short_s']), float(r['long_s']))], float(r['score']))
    for r in wide if r['in_tuning_grid'] == '1')
checks['frozen_config_still_rank_1'] = (int(wide[0]['threshold']), float(wide[0]['short_s']), float(wide[0]['long_s'])) == (3, .4, 2.)
history = {(t, s): v for (split, t, s, p), v in summary.items() if split == 'held_out' and p == 'history_adaptive'}
guard = read(DIAG / 'slack_guard_ablation.csv')
checks['diagnostic_scenarios_reproduce_all_15_primary_cells'] = len(guard) == 15 and all(
    math.isclose(float(r['with_guard_pct']), history[(r['template'], r['scenario'])]) for r in guard)
det = read(DIAG / 'detector_diagnostic.csv')
checks['detector_covers_all_heldout_regimes'] = {r['scenario'] for r in det} == {
    'held_iid_27', 'held_outage_extended', 'held_tight_17', 'held_quota_23', 'held_mixed'}
checks['outage_cause_only_in_outage_regime'] = all(r['scenario'] == 'held_outage_extended' for r in det if r['true_cause'] == 'outage')

sw = read(DIAG / 'switching_ablation_trials.csv')
swk = {(r['scenario'], r['template'], r['variant'], r['seed']): r['success'] for r in sw}
primary_rows = {(r['scenario'], r['template'], r['policy'], r['seed']): r['success'] for r in held}
checks['switching_trial_count'] = len(sw) == 5 * 3 * 200 * 6 == len(swk)
checks['switching_adaptive_and_references_match_primary_seed_for_seed'] = all(
    swk[(s, t, v, seed)] == primary_rows[(s, t, {'adaptive': 'history_adaptive'}.get(v, v), seed)]
    for (s, t, v, seed) in swk if v in ('adaptive', 'observable_cooldown', 'immediate'))
checks['perfect_detection_equals_short_only_without_outages'] = all(
    swk[(s, t, 'perfect_detection', seed)] == swk[(s, t, 'short_only', seed)]
    for (s, t, v, seed) in swk if v == 'short_only' and s != 'held_outage_extended')

assert all(checks.values()), {k: v for k, v in checks.items() if not v}
(ROOT / 'results' / 'audit.json').write_text(json.dumps({
    'checks': checks, 'all_pass': True,
    'trials': {'label_masking': len(lm), 'development': 12 * 360, 'heldout': len(held), 'unseen_dag': len(unseen),
               'history_window': len(window), 'outage_sweep': len(sweep), 'switching_ablation': len(sw), 'localhost_http': len(http)},
    'important': 'Synthetic simulations only; localhost HTTP uses injected faults, not provider traces'}, indent=2))
print(json.dumps(checks, indent=2))
