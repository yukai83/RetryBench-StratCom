import dataclasses
from pathlib import Path
import pytest

if not (Path(__file__).resolve().parents[1] / 'results' / 'main' / 'frozen_parameters.json').exists():
    pytest.skip('run run_main_study.py first: the diagnostics use its frozen configuration', allow_module_level=True)
import retrybench.simulator as simmod
from retrybench.policies import RetryContext, decide
from retrybench.stratcom import make_assessment_workload, simulate_assessment
import run_diagnostics as d


def ctx(**args):
    base = dict(error='transient', attempt_count=1, max_attempts=4, now=5., deadline=40.,
                calls_so_far=3, task_count=10, longest_remaining_chain=2, jitter=1.)
    base.update(args)
    return RetryContext(**base)


def test_instrumentation_is_passive_and_restores_policy_hook():
    w = d.workload_for(91003, 'information_environment_assessment', d.OUTAGE)
    cfg = dataclasses.replace(d.OUTAGE, **d.TUNED)
    plain, _ = simulate_assessment(w, cfg, 'history_adaptive')
    observed, decisions = d.instrumented_history_run(w, cfg)
    assert plain.record() == observed.record()
    assert simmod.decide is decide
    assert decisions and all(len(x) == 4 for x in decisions)


def test_detector_scores_true_cause_but_policy_sees_masked_label():
    seen = []

    def spy(policy, c):
        seen.append(c.error)
        return decide(policy, c)

    w = d.workload_for(91010, 'live_fact_check_support', d.OUTAGE)
    simmod.decide = spy
    try:
        simulate_assessment(w, dataclasses.replace(d.OUTAGE, **d.TUNED), 'history_adaptive')
    finally:
        simmod.decide = decide
    assert seen and 'outage' not in seen
    _, decisions = d.instrumented_history_run(w, dataclasses.replace(d.OUTAGE, **d.TUNED))
    assert any(cause == 'outage' for cause, *_ in decisions)


def test_slack_guard_ablation_only_changes_history_policy_near_deadline():
    near = ctx(now=9.95, deadline=10., recent_errors=0, adaptive_short_s=.4)
    assert not decide('history_adaptive', near).retry
    assert d._no_guard('history_adaptive', near).retry
    for pol in ('immediate', 'exponential', 'observable_cooldown', 'sdk_style_proxy'):
        assert d._no_guard(pol, near) == decide(pol, near)


def test_sweep_extension_matches_primary_heldout_transformation():
    base = make_assessment_workload(91000, 'communications_situation_report')
    w = d.workload_for(91000, 'communications_situation_report', d.OUTAGE, 2.)
    assert w.outage_windows == tuple((a, b + 2.) for a, b in base.outage_windows)
    assert d.workload_for(91000, 'communications_situation_report', d.HELD_OUT[0]).outage_windows == base.outage_windows


def test_switch_hook_pins_or_oracles_the_wait_and_leaves_other_policies_alone():
    tuned = dict(adaptive_threshold=3, adaptive_short_s=.4, adaptive_long_s=2.)
    transient, outage = ctx(error='transient', recent_errors=5, **tuned), ctx(error='outage', recent_errors=0, **tuned)
    assert d.switch_hook('short_only')('history_adaptive', transient).delay_s == .4
    assert d.switch_hook('long_only')('history_adaptive', ctx(error='transient', recent_errors=0, **tuned)).delay_s == 2.
    assert d.switch_hook('perfect_detection')('history_adaptive', outage).delay_s == 2.
    assert d.switch_hook('perfect_detection')('history_adaptive', transient).delay_s == .4
    assert d.switch_hook('adaptive')('history_adaptive', transient) == decide('history_adaptive', transient)
    for pol in ('immediate', 'exponential', 'observable_cooldown', 'sdk_style_proxy'):
        assert d.switch_hook('long_only')(pol, transient) == decide(pol, transient)


def test_tradeoff_hook_reproduces_frozen_controller_and_applies_rate_rule():
    tuned = dict(adaptive_threshold=3, adaptive_short_s=.4, adaptive_long_s=2.)
    record = []
    for errors, total in ((2, 6), (3, 6), (5, 12)):
        c = ctx(recent_errors=errors, recent_total=total, **tuned)
        assert d.tradeoff_hook(3, None, record)('history_adaptive', c) == decide('history_adaptive', c)
    rate = d.tradeoff_hook(3, .5, record)
    assert rate('history_adaptive', ctx(recent_errors=3, recent_total=10, **tuned)).delay_s == .4
    assert rate('history_adaptive', ctx(recent_errors=3, recent_total=5, **tuned)).delay_s == 2.
    for pol in ('immediate', 'exponential', 'observable_cooldown', 'sdk_style_proxy'):
        c = ctx(recent_errors=9, recent_total=9, **tuned)
        assert rate(pol, c) == decide(pol, c)


def test_tradeoff_frozen_rows_match_primary_cells_and_detector():
    import csv
    root = Path(__file__).resolve().parents[1] / 'results'
    path = root / 'diagnostics' / 'threshold_tradeoff.csv'
    if not path.exists():
        pytest.skip('run run_diagnostics.py first')
    frozen = [r for r in csv.DictReader(path.open()) if r['frozen'] == '1']
    held = {(r['template'], r['scenario']): float(r['success_pct']) for r in csv.DictReader((root / 'main' / 'heldout_summary.csv').open())
            if r['split'] == 'held_out' and r['policy'] == 'history_adaptive'}
    det = {(r['scenario'], r['true_cause']): r for r in csv.DictReader((root / 'diagnostics' / 'detector_diagnostic.csv').open())}
    assert len(frozen) == len(d.TRADEOFF_SCENARIOS)
    for r in frozen:
        for t in d.TEMPLATES:
            assert float(r[f'success_pct_{t}']) == held[(t, r['scenario'])]
        indep = [det[(r['scenario'], c)] for c in ('transient', 'timeout') if (r['scenario'], c) in det]
        share = 100 * sum(int(x['long_wait_retries']) for x in indep) / sum(int(x['scheduled_retries']) for x in indep)
        assert abs(share - float(r['long_wait_pct_independent'])) < .06
