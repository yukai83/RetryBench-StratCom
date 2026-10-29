from dataclasses import replace
from retrybench.model import Scenario
from retrybench.stratcom import make_assessment_workload, simulate_assessment
from retrybench.policies import RetryContext, decide


def test_outage_label_is_masked_but_true_events_still_logged():
    w=make_assessment_workload(2033)
    sc=Scenario('masked', failure_prob=.08,use_outages=True,deadline_s=45,mask_outages=True)
    _,r=simulate_assessment(w,sc,'budget_aware',log_events=True)
    outages=[e for e in r.events if e['event']=='attempt_failure' and e['error']=='outage']
    # This seed has an outage. The policy must see transient (5xx) only.
    assert outages
    assert all(e['observed_error']=='transient' for e in outages)


def test_unmasked_mode_keeps_default_behavior():
    w=make_assessment_workload(2033)
    sc=Scenario('same', failure_prob=.08,use_outages=True,deadline_s=45)
    a,r=simulate_assessment(w,sc,'budget_aware',log_events=True)
    b,r2=simulate_assessment(w,replace(sc,mask_outages=False),'budget_aware',log_events=True)
    assert a==b and r.record()==r2.record() and r.events==r2.events


def test_observable_policy_needs_no_oracle_outage_type():
    c=RetryContext('transient',1,4,8.,45.,3,10,3,1.)
    o=decide('observable_cooldown',c)
    oracle=decide('budget_aware',c)
    assert o.retry and oracle.retry
    assert o.delay_s > oracle.delay_s


def test_label_masking_never_changes_immediate_retry():
    w=make_assessment_workload(2035)
    sc=Scenario('same',failure_prob=.08,use_outages=True,deadline_s=45)
    a,_=simulate_assessment(w,sc,'immediate')
    b,_=simulate_assessment(w,replace(sc,mask_outages=True),'immediate')
    assert a.timely_evidence_complete==b.timely_evidence_complete
    assert a.calls==b.calls and a.elapsed_s==b.elapsed_s
