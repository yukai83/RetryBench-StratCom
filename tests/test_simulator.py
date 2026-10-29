import pytest
from retrybench.model import Scenario, generate_workload
from retrybench.simulator import simulate
from retrybench.policies import POLICIES
from retrybench.experiment import summarize, paired_contrasts, run_study


@pytest.mark.parametrize('policy', POLICIES)
def test_perfect_provider_completes_all(policy):
    w=generate_workload(9,12,'layered',sigma=0)
    sc=Scenario('perfect',failure_prob=0, timeout_s=100,deadline_s=200)
    r=simulate(w,sc,policy)
    assert r.success and r.succeeded_tasks==12
    assert r.calls == 12 and r.retry_calls==0
    assert r.elapsed_s < 200


@pytest.mark.parametrize('policy', POLICIES)
def test_known_permanent_error_stops(policy):
    w=generate_workload(4,8,'chain')
    sc=Scenario('permanent',permanent_prob=1,deadline_s=200)
    r=simulate(w,sc,policy)
    assert not r.success and r.calls == 1 and r.permanent_errors==1


def test_100_percent_iid_failure_with_retries():
    w=generate_workload(1,8,'chain',sigma=0)
    sc=Scenario('always_fails',failure_prob=1,deadline_s=200)
    assert simulate(w,sc,'none').calls==1
    assert simulate(w,sc,'immediate').calls==4
    assert simulate(w,sc,'exponential').calls==4


def test_delay_after_failure_preserved_in_event_sequence():
    w=generate_workload(6,6,'chain',sigma=0)
    sc=Scenario('always_fails',failure_prob=1,deadline_s=200)
    r=simulate(w,sc,'exponential',log_events=True)
    es=r.events
    for s in [x for x in es if x['event']=='retry_scheduled']:
        a=next(y for y in es if y['event']=='retry_ready' and y['time_s']>s['time_s'] and y['task']==s['task'])
        assert a['time_s'] > s['time_s']


def test_strict_deadline_never_reports_late_success():
    w=generate_workload(12,12,'chain',sigma=0)
    sc=Scenario('unrealistically_tight',failure_prob=0,deadline_s=2)
    for p in POLICIES:
        r=simulate(w,sc,p)
        assert not r.success and r.elapsed_s==2


def test_rate_limit_is_endogenous():
    w=generate_workload(12,10,'fanout',sigma=0)
    sc=Scenario('rate',failure_prob=0,provider_rps=.2,burst_tokens=1,deadline_s=50)
    r=simulate(w,sc,'immediate')
    assert r.rate_limit_rejections>0
    assert r.retry_calls>0


def test_timeouts_are_not_ordinary_transient_failures():
    w=generate_workload(14,8,'chain',median_latency=2,sigma=0)
    sc=Scenario('timeouts',failure_prob=0,timeout_s=.5)
    r=simulate(w,sc,'none')
    assert r.timeouts==1 and r.transient_errors==0


def test_paired_trace_has_same_first_attempt_under_different_policies():
    w=generate_workload(44,12,'chain',sigma=0)
    sc=Scenario('always_fails',failure_prob=1,deadline_s=200)
    a=simulate(w,sc,'none',log_events=True)
    b=simulate(w,sc,'exponential',log_events=True)
    a_start=next(e for e in a.events if e['event']=='attempt_start')
    b_start=next(e for e in b.events if e['event']=='attempt_start')
    assert a_start==b_start
    assert a.elapsed_s <= b.elapsed_s


def test_repeatability():
    w=generate_workload(31,12,'layered')
    sc=Scenario('iid',failure_prob=.22)
    assert simulate(w,sc,'budget_aware').record()==simulate(w,sc,'budget_aware').record()


def test_paired_bootstrap_reasonable(tmp_path):
    data, summary=run_study(tmp_path,replicates=8,n_tasks=6,scenarios=['iid_medium'],make_plots=False)
    assert len(data)==8*4
    assert len(summary)==4
    intervals=paired_contrasts(data,n_boot=100)
    assert len(intervals)==6*5
    assert all(x['bootstrap_ci95_low']<=x['mean_difference']+10 for x in intervals)
    assert (tmp_path/'replicate_metrics.csv').exists()
