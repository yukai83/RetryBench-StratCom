"""Post-hoc diagnostics reported in the paper (Table IV, Fig. 3 and Section V).

Every analysis here is post hoc and exploratory. None of them changes the
frozen controller configuration in results/main/frozen_parameters.json, and
none is used to select a policy. The hidden outage label is read only to SCORE
the controller's state (detector diagnostic), with one deliberate exception: the
perfect-detection variant of the switching ablation lets the label choose the
wait, as an upper bound on what better detection could achieve. It is not a
deployable policy.

Outputs (results/diagnostics/):
  outage_duration_trials.csv / _summary.csv / _paired.csv
      Held-out extended-outage scenario with the outage-window extension swept
      over 0, 1, 2, 3, 4 and 6 simulated seconds (+2 s is the primary test).
  detector_diagnostic.csv
      Share of scheduled history-adaptive retries that used the long wait,
      split by the simulator's true failure cause, on the five held-out regimes.
  wide_development_grid.csv
      120-configuration grid on development seeds only (robustness of selection).
  slack_guard_ablation.csv
      History-adaptive with and without its 0.1 s deadline-slack guard.
  sdk_proxy_cap_binding.csv
      How often the sdk_style_proxy call cap stopped a retry on held-out trials.
  switching_ablation_trials.csv / _summary.csv / _paired.csv
      The frozen controller against its own two waits used alone (short only,
      long only) and against perfect outage detection with the same waits, with
      linear cooldown and immediate retry rerun as references.

Run from the project root:  python run_diagnostics.py
"""
from __future__ import annotations
import csv, dataclasses, json, collections
from pathlib import Path
from statistics import mean
import numpy as np
import retrybench.simulator as simmod
from retrybench.model import Scenario
from retrybench.policies import decide as policy_decide
from retrybench.stratcom import make_assessment_workload, simulate_assessment

ROOT = Path(__file__).parent
OUT = ROOT / 'results' / 'diagnostics'
TEMPLATES = ['information_environment_assessment', 'live_fact_check_support', 'communications_situation_report']
POLICIES = ('immediate', 'exponential', 'observable_cooldown', 'sdk_style_proxy', 'history_adaptive')
TEST_SEEDS = range(91000, 91200)
DEV_SEEDS = range(61100, 61140)
EXTENSIONS = (0., 1., 2., 3., 4., 6.)
FROZEN = json.loads((ROOT / 'results' / 'main' / 'frozen_parameters.json').read_text())['frozen_adaptive']
TUNED = dict(adaptive_threshold=int(FROZEN['threshold']), adaptive_short_s=FROZEN['short_s'],
             adaptive_long_s=FROZEN['long_s'])

# Identical to run_main_study.test(): the held-out scenario definitions.
HELD_OUT = [Scenario('held_iid_27', failure_prob=.27, deadline_s=26, mask_outages=True),
            Scenario('held_outage_extended', failure_prob=.10, deadline_s=48, use_outages=True, mask_outages=True),
            Scenario('held_tight_17', failure_prob=.17, deadline_s=14, mask_outages=True),
            Scenario('held_quota_23', failure_prob=.09, deadline_s=52, provider_rps=2.3, burst_tokens=2,
                     advertise_retry_after=True, mask_outages=True),
            Scenario('held_mixed', failure_prob=.2, permanent_prob=.02, deadline_s=40, mask_outages=True)]
OUTAGE = HELD_OUT[1]
DEV_CASES = [Scenario('dev_iid', failure_prob=.22, deadline_s=22, mask_outages=True),
             Scenario('dev_outage', failure_prob=.07, deadline_s=45, use_outages=True, mask_outages=True),
             Scenario('dev_quota', failure_prob=.08, deadline_s=55, provider_rps=1.8, burst_tokens=2,
                      advertise_retry_after=True, mask_outages=True)]


def workload_for(seed: int, template: str, scenario: Scenario, extension: float = 2.):
    w = make_assessment_workload(seed, template)
    if scenario.name == 'held_outage_extended':
        w = dataclasses.replace(w, outage_windows=tuple((a, b + extension) for a, b in w.outage_windows))
    return w


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open('w', newline='', encoding='utf8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def paired_ci(diff: np.ndarray, salt: str) -> tuple[float, float]:
    # Same deterministic seed-resampling bootstrap as run_main_study.report().
    rng = np.random.default_rng(2027 + sum(map(ord, salt)))
    boots = diff[rng.integers(0, len(diff), size=(2000, len(diff)))].mean(axis=1) * 100
    return round(float(np.percentile(boots, 2.5)), 2), round(float(np.percentile(boots, 97.5)), 2)


def outage_duration_sweep():
    cfg = dataclasses.replace(OUTAGE, **TUNED)
    rows = []
    for ext in EXTENSIONS:
        for template in TEMPLATES:
            for seed in TEST_SEEDS:
                w = workload_for(seed, template, OUTAGE, ext)
                for pol in POLICIES:
                    m, _ = simulate_assessment(w, cfg, pol)
                    rows.append({'extension_s': ext, 'template': template, 'seed': seed, 'policy': pol,
                                 'success': int(m.timely_evidence_complete), 'calls': m.calls})
    write_csv(OUT / 'outage_duration_trials.csv', rows)
    cell = collections.defaultdict(dict)
    for r in rows:
        cell[(r['extension_s'], r['template'], r['policy'])][r['seed']] = r['success']
    summary, paired = [], []
    for ext in EXTENSIONS:
        for template in TEMPLATES:
            for pol in POLICIES:
                v = cell[(ext, template, pol)]
                summary.append({'extension_s': ext, 'template': template, 'policy': pol, 'n': len(v),
                                'success_pct': round(100 * mean(v.values()), 2)})
            h = cell[(ext, template, 'history_adaptive')]
            for other in ('observable_cooldown', 'exponential'):
                o = cell[(ext, template, other)]
                diff = np.array([h[s] - o[s] for s in TEST_SEEDS], dtype=float)
                # At +2 s the salt equals run_main_study's, so the primary-test CIs match exactly.
                salt = template + 'held_outage_extended' + other + ('' if ext == 2. else f'@{ext:g}')
                lo, hi = paired_ci(diff, salt)
                paired.append({'extension_s': ext, 'template': template, 'compared_with': other, 'n_paired': len(diff),
                               'difference_pp': round(100 * diff.mean(), 2), 'ci_low': lo, 'ci_high': hi})
    write_csv(OUT / 'outage_duration_summary.csv', summary)
    write_csv(OUT / 'outage_duration_paired.csv', paired)
    return summary, paired


def instrumented_history_run(workload, cfg):
    """Run history_adaptive while recording the controller state at each decision.

    The wrapper only observes the RetryContext the policy already receives; the
    true cause is read afterwards from the simulator's audit log for scoring.
    """
    record = []

    def spy(policy, ctx):
        decision = policy_decide(policy, ctx)
        record.append((ctx.recent_errors >= ctx.adaptive_threshold, decision.retry, decision.reason))
        return decision

    simmod.decide = spy
    try:
        metrics, result = simulate_assessment(workload, cfg, 'history_adaptive', log_events=True)
    finally:
        simmod.decide = policy_decide
    failures = [e for e in result.events if e['event'] == 'attempt_failure']
    if len(failures) != len(record):
        raise AssertionError('Decision/failure alignment broken')
    return metrics, [(f['error'], *rec) for f, rec in zip(failures, record)]


def detector_diagnostic():
    counts = collections.Counter()
    for sc in HELD_OUT:
        cfg = dataclasses.replace(sc, **TUNED)
        for template in TEMPLATES:
            for seed in TEST_SEEDS:
                _, decisions = instrumented_history_run(workload_for(seed, template, sc), cfg)
                for true_cause, high, retried, reason in decisions:
                    if retried and true_cause in ('transient', 'timeout', 'outage'):
                        counts[(sc.name, true_cause, high)] += 1
    rows = []
    for sc in HELD_OUT:
        for cause in ('transient', 'timeout', 'outage'):
            hi, lo = counts[(sc.name, cause, True)], counts[(sc.name, cause, False)]
            if hi + lo:
                rows.append({'scenario': sc.name, 'true_cause': cause, 'scheduled_retries': hi + lo,
                             'long_wait_retries': hi, 'long_wait_pct': round(100 * hi / (hi + lo), 1)})
    write_csv(OUT / 'detector_diagnostic.csv', rows)
    return rows


def wide_development_grid():
    rows = []
    for k in (2, 3, 4, 5):
        for short in (.2, .4, .6, .8, 1.0, 1.5):
            for long in (1., 1.5, 2., 2.5, 3.):
                y, calls = [], []
                for seed in DEV_SEEDS:
                    for template in TEMPLATES:
                        w = make_assessment_workload(seed, template)
                        for sc in DEV_CASES:
                            cfg = dataclasses.replace(sc, adaptive_threshold=k, adaptive_short_s=short, adaptive_long_s=long)
                            m, _ = simulate_assessment(w, cfg, 'history_adaptive')
                            y.append(m.timely_evidence_complete)
                            calls.append(m.calls)
                rows.append({'threshold': k, 'short_s': short, 'long_s': long, 'n': len(y),
                             'score': mean(y), 'mean_calls': mean(calls),
                             'in_tuning_grid': int(k in (2, 3) and short in (.2, .4) and long in (1., 1.5, 2.))})
    rows.sort(key=lambda x: (-x['score'], x['mean_calls'], x['threshold'], x['long_s']))
    for rank, r in enumerate(rows, 1):
        r['rank'] = rank
    write_csv(OUT / 'wide_development_grid.csv', rows)
    return rows


def _no_guard(policy, ctx):
    if policy != 'history_adaptive' or ctx.now >= ctx.deadline:
        return policy_decide(policy, ctx)
    return policy_decide(policy, dataclasses.replace(ctx, deadline=ctx.deadline + 1e6))


def slack_guard_ablation():
    rows = []
    for sc in HELD_OUT:
        cfg = dataclasses.replace(sc, **TUNED)
        for template in TEMPLATES:
            with_g, without_g = [], []
            for seed in TEST_SEEDS:
                w = workload_for(seed, template, sc)
                a, _ = simulate_assessment(w, cfg, 'history_adaptive')
                simmod.decide = _no_guard
                try:
                    b, _ = simulate_assessment(w, cfg, 'history_adaptive')
                finally:
                    simmod.decide = policy_decide
                with_g.append(a.timely_evidence_complete)
                without_g.append(b.timely_evidence_complete)
            rows.append({'scenario': sc.name, 'template': template, 'n': len(with_g),
                         'with_guard_pct': round(100 * mean(with_g), 2), 'without_guard_pct': round(100 * mean(without_g), 2),
                         'seeds_differing': sum(x != y for x, y in zip(with_g, without_g))})
    write_csv(OUT / 'slack_guard_ablation.csv', rows)
    return rows


def sdk_proxy_cap_binding():
    rows = []
    for sc in HELD_OUT:
        cfg = dataclasses.replace(sc, **TUNED)
        for template in TEMPLATES:
            bound = same = 0
            for seed in TEST_SEEDS:
                w = workload_for(seed, template, sc)
                p, res = simulate_assessment(w, cfg, 'sdk_style_proxy', log_events=True)
                e, _ = simulate_assessment(w, cfg, 'exponential')
                bound += any(ev.get('reason') == 'sdk_style_retry_quota' for ev in res.events)
                same += p.timely_evidence_complete == e.timely_evidence_complete
            rows.append({'scenario': sc.name, 'template': template, 'n': len(TEST_SEEDS),
                         'cap_bound_trials': bound, 'same_outcome_as_exponential': same})
    write_csv(OUT / 'sdk_proxy_cap_binding.csv', rows)
    return rows


SWITCH_VARIANTS = ('adaptive', 'short_only', 'long_only', 'perfect_detection')
SWITCH_REFERENCES = ('observable_cooldown', 'immediate')
SWITCH_CONTRASTS = (('adaptive', 'short_only'), ('adaptive', 'long_only'), ('perfect_detection', 'adaptive'),
                    ('perfect_detection', 'observable_cooldown'), ('perfect_detection', 'immediate'),
                    ('short_only', 'immediate'))


def switch_hook(variant):
    """Policy hook that fixes how the history controller picks between its short and long wait.

    short_only / long_only pin the state; perfect_detection picks the long wait exactly when the
    true cause is an outage (the run is unmasked so the policy receives that label). The waits
    themselves are unchanged. Other policies pass through untouched.
    """
    def hook(policy, ctx):
        if policy == 'history_adaptive' and variant != 'adaptive':
            if variant == 'short_only':
                ctx = dataclasses.replace(ctx, recent_errors=0)
            elif variant == 'long_only':
                ctx = dataclasses.replace(ctx, recent_errors=ctx.adaptive_threshold)
            elif variant == 'perfect_detection':
                ctx = dataclasses.replace(ctx, recent_errors=ctx.adaptive_threshold if ctx.error == 'outage' else 0)
            else:
                raise ValueError(variant)
        return policy_decide(policy, ctx)
    return hook


def switching_ablation():
    rows = []
    for sc in HELD_OUT:
        cfg = dataclasses.replace(sc, **TUNED)
        for template in TEMPLATES:
            for seed in TEST_SEEDS:
                w = workload_for(seed, template, sc)
                for variant in SWITCH_VARIANTS:
                    run_cfg = dataclasses.replace(cfg, mask_outages=False) if variant == 'perfect_detection' else cfg
                    simmod.decide = switch_hook(variant)
                    try:
                        m, _ = simulate_assessment(w, run_cfg, 'history_adaptive')
                    finally:
                        simmod.decide = policy_decide
                    rows.append({'scenario': sc.name, 'template': template, 'seed': seed, 'variant': variant,
                                 'success': int(m.timely_evidence_complete)})
                for pol in SWITCH_REFERENCES:
                    m, _ = simulate_assessment(w, cfg, pol)
                    rows.append({'scenario': sc.name, 'template': template, 'seed': seed, 'variant': pol,
                                 'success': int(m.timely_evidence_complete)})
    write_csv(OUT / 'switching_ablation_trials.csv', rows)
    cell = collections.defaultdict(dict)
    for r in rows:
        cell[(r['scenario'], r['template'], r['variant'])][r['seed']] = r['success']
    summary, paired = [], []
    for sc in HELD_OUT:
        for template in TEMPLATES:
            for variant in SWITCH_VARIANTS + SWITCH_REFERENCES:
                v = cell[(sc.name, template, variant)]
                summary.append({'scenario': sc.name, 'template': template, 'variant': variant, 'n': len(v),
                                'success_pct': round(100 * mean(v.values()), 2)})
            for a, b in SWITCH_CONTRASTS:
                diff = np.array([cell[(sc.name, template, a)][s] - cell[(sc.name, template, b)][s] for s in TEST_SEEDS], dtype=float)
                lo, hi = paired_ci(diff, f'switch{template}{sc.name}{a}{b}')
                paired.append({'scenario': sc.name, 'template': template, 'variant': a, 'compared_with': b,
                               'n_paired': len(diff), 'difference_pp': round(100 * diff.mean(), 2), 'ci_low': lo, 'ci_high': hi})
    write_csv(OUT / 'switching_ablation_summary.csv', summary)
    write_csv(OUT / 'switching_ablation_paired.csv', paired)
    return summary


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    summary, paired = outage_duration_sweep()
    det = detector_diagnostic()
    grid = wide_development_grid()
    guard = slack_guard_ablation()
    cap = sdk_proxy_cap_binding()
    switch = switching_ablation()
    frozen_row = next(r for r in grid if (r['threshold'], r['short_s'], r['long_s']) == (3, .4, 2.))
    manifest = {
        'status': 'post-hoc exploratory diagnostics; frozen configuration unchanged',
        'frozen_configuration': FROZEN,
        'outage_sweep': {'extensions_s': list(EXTENSIONS), 'seeds': '91000..91199', 'trials': len(EXTENSIONS) * 3 * 200 * len(POLICIES)},
        'detector_note': 'hidden outage label used only to score controller state, never as policy input',
        'wide_grid': {'configs': len(grid), 'dev_seeds': '61100..61139', 'frozen_config_rank': frozen_row['rank']},
        'slack_guard_total_seed_differences': sum(r['seeds_differing'] for r in guard),
        'sdk_proxy_cap_bound_trials': sum(r['cap_bound_trials'] for r in cap),
        'sdk_proxy_same_as_exponential_trials': sum(r['same_outcome_as_exponential'] for r in cap),
        'sdk_proxy_trials': sum(r['n'] for r in cap),
        'switching_ablation_trials': sum(r['n'] for r in switch),
        'switching_note': 'perfect_detection reads the true outage label by design; it is an upper bound, not a deployable policy',
    }
    (OUT / 'diagnostics_manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    for r in det:
        print('DETECTOR', r)
