"""Load feedback (Scenario.outage_load_delay_s): requests received during an outage delay its end."""
import dataclasses
import pytest
from retrybench.model import Scenario, Workload, generate_workload
from retrybench.simulator import simulate
from retrybench.stratcom import make_assessment_workload, simulate_assessment

OUTAGE = Scenario('outage', failure_prob=.1, use_outages=True, mask_outages=True, deadline_s=48,
                  adaptive_threshold=3, adaptive_short_s=.4, adaptive_long_s=2.)
POLICIES = ('immediate', 'exponential', 'observable_cooldown', 'sdk_style_proxy', 'history_adaptive')


@pytest.mark.parametrize('policy', POLICIES)
def test_zero_delay_reproduces_scheduled_outages(policy):
    for seed in (91000, 91007, 91123):
        w = make_assessment_workload(seed, 'information_environment_assessment')
        a, _ = simulate_assessment(w, OUTAGE, policy)
        b, _ = simulate_assessment(w, dataclasses.replace(OUTAGE, outage_load_delay_s=0.), policy)
        assert a.record() == b.record()


def test_negative_delay_rejected():
    with pytest.raises(ValueError):
        Scenario('bad', outage_load_delay_s=-.1)


def test_delay_has_no_effect_without_outages():
    w = make_assessment_workload(91001, 'live_fact_check_support')
    iid = Scenario('iid', failure_prob=.27, deadline_s=26, mask_outages=True)
    for policy in POLICIES:
        a, _ = simulate_assessment(w, iid, policy)
        b, _ = simulate_assessment(w, dataclasses.replace(iid, outage_load_delay_s=1.), policy)
        assert a.record() == b.record()


def test_request_after_scheduled_end_fails_when_retries_prolonged_the_outage():
    # One-task chain, outage [0, 1) s: immediate retry sends four requests at t = 0, 0.2, 0.4, 0.6.
    base = generate_workload(5, 4, 'chain', sigma=0)
    w = Workload(base.tasks, base.attempts, base.permanent_draws, ((0., 1.), (100., 101.)), base.seed, base.shape)
    sc = Scenario('o', failure_prob=0., use_outages=True, deadline_s=60)
    plain = simulate(w, sc, 'exponential', log_events=True)
    # Exponential backoff's first retry arrives at 0.2 + 0.8 s = 1.0 s, just after the scheduled end.
    loaded = simulate(w, dataclasses.replace(sc, outage_load_delay_s=.5), 'exponential', log_events=True)
    assert plain.outage_errors == 1 and loaded.outage_errors > plain.outage_errors
    starts = [e for e in loaded.events if e['event'] == 'attempt_start' and e['task'] == 0]
    assert starts[1]['time_s'] >= 1. and starts[1]['expected_response'] == 'outage'


def test_outage_end_moves_by_delta_per_request():
    base = generate_workload(5, 4, 'chain', sigma=0)
    w = Workload(base.tasks, base.attempts, base.permanent_draws, ((0., 1.), (100., 101.)), base.seed, base.shape)
    sc = Scenario('o', failure_prob=0., use_outages=True, deadline_s=60, outage_load_delay_s=.25)
    r = simulate(w, sc, 'immediate', log_events=True)
    # Four immediate requests at 0, 0.2, 0.4, 0.6 s each push the end out by 0.25 s; all fail.
    assert r.outage_errors == 4 and not r.success
    times = [e['time_s'] for e in r.events if e['event'] == 'attempt_start']
    assert times == pytest.approx([0., .2, .4, .6])
