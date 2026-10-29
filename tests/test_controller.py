import dataclasses
from retrybench.model import Scenario,generate_workload
from retrybench.policies import RetryContext,decide
from retrybench.simulator import simulate
from retrybench.stratcom import make_assessment_workload,simulate_assessment


def ctx(**args):
    base=dict(error='transient',attempt_count=1,max_attempts=4,now=5.,deadline=40.,
              calls_so_far=3,task_count=10,longest_remaining_chain=2,jitter=1.)
    base.update(args)
    return RetryContext(**base)

def test_history_threshold_changes_only_observed_error_based_wait():
    low=decide('history_adaptive',ctx(recent_errors=2,adaptive_threshold=3,adaptive_short_s=.4,adaptive_long_s=2.))
    high=decide('history_adaptive',ctx(recent_errors=3,adaptive_threshold=3,adaptive_short_s=.4,adaptive_long_s=2.))
    assert low.retry and high.retry and low.delay_s == .4 and high.delay_s == 2.

def test_rate_limit_hint_is_obeyed_by_adaptive_controller():
    d=decide('history_adaptive',ctx(error='rate_limit',retry_after_s=3.7))
    assert d.retry and d.delay_s>=3.7

def test_permanent_failure_never_retried_by_adaptive_controller():
    assert not decide('history_adaptive',ctx(error='permanent')).retry

def test_remaining_deadline_blocks_impossible_retry():
    d=decide('history_adaptive',ctx(now=9.9,deadline=10,recent_errors=4))
    assert not d.retry

def test_sdk_style_proxy_is_a_limited_proxy():
    d=decide('sdk_style_proxy',ctx(calls_so_far=100))
    assert not d.retry

def test_adaptive_results_repeat_exactly():
    w=make_assessment_workload(92353)
    s=Scenario('hidden_outage',use_outages=True,mask_outages=True,deadline_s=45)
    a,_=simulate_assessment(w,s,'history_adaptive')
    b,_=simulate_assessment(w,s,'history_adaptive')
    assert a.record()==b.record()

def test_masked_outage_never_in_policy_error_log():
    w=generate_workload(112,7)
    s=Scenario('hid',use_outages=True,mask_outages=True,deadline_s=45)
    r=simulate(w,s,'history_adaptive',log_events=True)
    observed=[e['observed_error'] for e in r.events if e['event']=='attempt_failure']
    assert 'outage' not in observed

def test_exponential_not_affected_by_adaptive_params():
    w=make_assessment_workload(1192)
    s=Scenario('masked',use_outages=True,mask_outages=True,deadline_s=45)
    a,_=simulate_assessment(w,s,'exponential')
    b,_=simulate_assessment(w,dataclasses.replace(s,adaptive_threshold=5,adaptive_long_s=10.),'exponential')
    assert a.record()==b.record()
