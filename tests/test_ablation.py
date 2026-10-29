"""Cooldown policy variants must isolate each guard without changing the cooldown itself."""
from retrybench.policies import RetryContext, decide, ABLATION_POLICIES, POLICIES
from retrybench.stratcom import make_assessment_workload, simulate_assessment
from retrybench.scenarios import MAIN_SCENARIOS


def context(**kwargs):
    d=dict(error='outage',attempt_count=1,max_attempts=4,now=5.0,
           deadline=45.0,calls_so_far=2,task_count=10,
           longest_remaining_chain=3,jitter=1.0,retry_after_s=None)
    d.update(kwargs)
    return RetryContext(**d)


def test_ablation_policies_not_in_main_four():
    assert set(ABLATION_POLICIES).isdisjoint(POLICIES)


def test_cooldown_identical_when_guards_nonbinding():
    ds=[decide(x,context()) for x in ('cooldown_only','cooldown_call_cap','cooldown_deadline_guard','budget_aware')]
    assert all(d.retry for d in ds)
    assert len({d.delay_s for d in ds})==1


def test_call_budget_guard_isolated():
    assert decide('cooldown_only',context(calls_so_far=100)).retry
    assert not decide('cooldown_call_cap',context(calls_so_far=100)).retry
    assert decide('cooldown_deadline_guard',context(calls_so_far=100)).retry
    assert not decide('budget_aware',context(calls_so_far=100)).retry


def test_deadline_guard_isolated():
    # All have future retry time before deadline, but only D-enabled policies
    # reject because the assumed remaining chain cannot finish by deadline.
    c=context(now=10.0,deadline=13.0,longest_remaining_chain=4)
    assert decide('cooldown_only',c).retry
    assert decide('cooldown_call_cap',c).retry
    assert not decide('cooldown_deadline_guard',c).retry
    assert not decide('budget_aware',c).retry


def test_policy_regression_three_scenarios():
    w=make_assessment_workload(2026,'information_environment_assessment')
    for sc in (MAIN_SCENARIOS[2],MAIN_SCENARIOS[4],MAIN_SCENARIOS[5]):
        for p in POLICIES:
            first,_=simulate_assessment(w,sc,p)
            second,_=simulate_assessment(w,sc,p)
            assert first.record()==second.record()
