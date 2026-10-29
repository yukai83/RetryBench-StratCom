import pytest
from retrybench.policies import RetryContext, decide, POLICIES


def ctx(**overrides):
    base = dict(error='transient', attempt_count=1, max_attempts=4, now=3.0,
                deadline=40., calls_so_far=5, task_count=12,
                longest_remaining_chain=3, jitter=1.)
    base.update(overrides)
    return RetryContext(**base)


def test_no_retry_declines():
    assert not decide('none',ctx()).retry


def test_immediate_has_zero_delay():
    d=decide('immediate',ctx())
    assert d.retry and d.delay_s == 0


def test_exponential_monotone_delay():
    delay=[decide('exponential',ctx(attempt_count=i)).delay_s for i in range(1,4)]
    assert delay==[.8,1.6,3.2]


@pytest.mark.parametrize('policy', POLICIES)
def test_permanent_never_retryable(policy):
    assert not decide(policy,ctx(error='permanent')).retry


def test_budget_aware_observes_deadline_and_quota():
    assert not decide('budget_aware',ctx(now=37., longest_remaining_chain=4)).retry
    assert not decide('budget_aware',ctx(calls_so_far=22)).retry
    assert decide('budget_aware',ctx()).retry


def test_unknown_policy_rejected():
    with pytest.raises(ValueError):
        decide('surprise',ctx())
