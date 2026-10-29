"""Structural safety and metric tests; synthetic tool success != factual truth."""
from dataclasses import replace
import csv
import json
import pytest
from retrybench.model import Workload, Task, Scenario, Attempt
from retrybench.policies import POLICIES, RetryContext, decide
from retrybench.simulator import TokenBucket, simulate
from retrybench.stratcom import (
    TEMPLATES, make_assessment_workload, assess_result, simulate_assessment,
    run_assessment_study,
)


@pytest.mark.parametrize('template', sorted(TEMPLATES))
def test_template_contains_evidence_sources_optional_handoff(template):
    w = make_assessment_workload(9, template)
    assert any(t.evidence_gate and t.criticality == 'mandatory' for t in w.tasks)
    assert any(t.freshness_ttl_s is not None for t in w.tasks)
    assert any(t.criticality == 'optional' for t in w.tasks)
    assert any(t.name == 'queue_human_review' for t in w.tasks)
    assert all(t.criticality == 'mandatory' or not t.evidence_gate for t in w.tasks)


@pytest.mark.parametrize('template', sorted(TEMPLATES))
@pytest.mark.parametrize('policy', POLICIES)
def test_clean_provider_delivers_full_brief(template, policy):
    w = make_assessment_workload(5, template, sigma=0)
    sc = Scenario('zero_fail', failure_prob=0, timeout_s=100, deadline_s=200)
    metrics, raw = simulate_assessment(w, sc, policy)
    assert metrics.status == 'full' and metrics.timely_evidence_complete
    assert metrics.optional_missing == 0 and raw.calls == len(w.tasks)
    assert metrics.mandatory_sources_fresh


def controlled(seed=21):
    """Make guaranteed, non-random attempt outcomes to isolate task semantics."""
    w = make_assessment_workload(seed, sigma=0)
    traces = tuple(tuple(Attempt(1., .99, 1.) for _ in trace) for trace in w.attempts)
    return replace(w, attempts=traces, permanent_draws=tuple(1. for _ in w.tasks))


def test_optional_permanent_failure_yields_labelled_partial_without_unverified_claim():
    w = controlled()
    draws = tuple(0. if t.criticality == 'optional' else 1. for t in w.tasks)
    w = replace(w, permanent_draws=draws)
    sc = Scenario('optional_fail', permanent_prob=.5, failure_prob=0,
                  timeout_s=100, deadline_s=200)
    metrics, raw = simulate_assessment(w, sc, 'none', log_events=True)
    assert metrics.status == 'partial' and metrics.brief_delivered
    assert metrics.evidence_checks_completed and metrics.timely_evidence_complete
    assert metrics.optional_completed == 0 and metrics.optional_missing == 2
    assert len([e for e in raw.events if e['event']=='optional_task_failure']) == 2
    assert not metrics.all_tasks_completed


def test_mandatory_evidence_task_failure_never_delivers():
    w = controlled()
    eid = next(t.task_id for t in w.tasks if t.evidence_gate)
    draws = tuple(0. if i == eid else 1. for i in range(len(w.tasks)))
    w = replace(w, permanent_draws=draws)
    metrics, raw = simulate_assessment(w, Scenario('evidence_fail', failure_prob=0,
                              permanent_prob=.5, deadline_s=200), 'none')
    assert not metrics.brief_delivered
    assert not metrics.evidence_checks_completed
    assert not metrics.timely_evidence_complete
    assert metrics.status == 'failed' and not raw.success


def test_successful_but_stale_brief_is_not_timely_evidence_complete():
    w = controlled()
    tasks = tuple(replace(t, freshness_ttl_s=.1) if t.freshness_ttl_s is not None else t
                  for t in w.tasks)
    w = replace(w, tasks=tasks)
    m, _ = simulate_assessment(w, Scenario('stale', failure_prob=0, timeout_s=100,
                                          deadline_s=200), 'none')
    assert m.brief_delivered and m.evidence_checks_completed
    assert not m.mandatory_sources_fresh and not m.timely_evidence_complete
    assert m.freshness_max_age_s is not None and m.freshness_max_age_s > .1


def test_optional_work_expires_at_deadline_but_required_brief_delivered():
    w = controlled()
    traces = tuple(tuple(replace(a, latency=40.) if w.tasks[i].criticality == 'optional'
                         else a for a in trace) for i, trace in enumerate(w.attempts))
    w = replace(w, attempts=traces)
    sc = Scenario('optional_deadline', failure_prob=0, timeout_s=100, deadline_s=15, workers=4)
    metrics, raw = simulate_assessment(w, sc, 'none', log_events=True)
    assert metrics.status == 'partial' and metrics.brief_delivered
    assert metrics.optional_missing == 2 and metrics.elapsed_s == 15
    assert any(e['event'] == 'brief_delivered' for e in raw.events)


def test_deadline_before_mandatory_handoff_cannot_deliver():
    w = controlled()
    m, _ = simulate_assessment(w, Scenario('deadline', failure_prob=0,
                                          deadline_s=1.1), 'none')
    assert m.status == 'failed' and not m.timely_evidence_complete


def test_optional_predecessor_for_required_task_rejected():
    with pytest.raises(ValueError, match='Mandatory tasks cannot depend'):
        Workload(tasks=(Task(0, (), criticality='optional'), Task(1, (0,))),
                 attempts=((Attempt(1, .9, 1),), (Attempt(1, .9, 1),)),
                 permanent_draws=(.9, .9), outage_windows=(), seed=1, shape='custom')


def test_rate_limit_hint_is_observed_and_backoff_follows_it():
    w = controlled()
    scenario = Scenario('hint', failure_prob=0, provider_rps=.2, burst_tokens=1,
                        advertise_retry_after=True, deadline_s=100, workers=4)
    metrics, raw = simulate_assessment(w, scenario, 'exponential', log_events=True)
    fails = [e for e in raw.events if e['event'] == 'attempt_failure' and e['error']=='rate_limit']
    assert fails and all(e['retry_after_s'] > 0 for e in fails)
    for failure in fails:
        matches = [e for e in raw.events if e['event'] == 'retry_scheduled'
                   and e['task']==failure['task'] and e['time_s'] == failure['time_s']]
        if matches:
            assert matches[0]['delay_s'] + 1e-5 >= failure['retry_after_s']


def test_no_hint_keeps_default_policy_delay():
    base = RetryContext(error='rate_limit', attempt_count=1, max_attempts=4, now=1.,
                        deadline=100., calls_so_far=1, task_count=10,
                        longest_remaining_chain=2, jitter=1.)
    assert decide('exponential', base).delay_s == .8
    assert decide('exponential', replace(base,retry_after_s=7.)).delay_s == 7.
    assert decide('budget_aware', replace(base,retry_after_s=7.)).delay_s >= 7.
    assert decide('immediate', replace(base,retry_after_s=7.)).delay_s == 0.


def test_token_bucket_wait_is_nonnegative():
    b = TokenBucket(capacity=1,rate=.25)
    assert b.accept(0)
    assert not b.accept(0)
    assert b.retry_after_s() == pytest.approx(4.0)
    assert b.accept(4.)


def test_repeatable_stratcom_metrics_and_event_log():
    w = make_assessment_workload(222)
    sc = Scenario('iid', failure_prob=.15,deadline_s=30.)
    a, raw_a = simulate_assessment(w, sc, 'budget_aware', log_events=True)
    b, raw_b = simulate_assessment(w, sc, 'budget_aware', log_events=True)
    assert a == b and raw_a.events == raw_b.events


def test_assessment_study_paired_and_manifest(tmp_path):
    rows = run_assessment_study(tmp_path, replicates=3, seed=10)
    assert len(rows) == 12
    with (tmp_path / 'stratcom_replicate_metrics.csv').open() as f:
        replicates = list(csv.DictReader(f))
    assert len(replicates) == 3 * 3 * 4
    assert len({(r['scenario'],r['seed'],r['policy']) for r in replicates}) == len(replicates)
    manifest=json.loads((tmp_path / 'stratcom_manifest.json').read_text())
    assert manifest['source_accuracy'].startswith('Not represented')


def test_failed_optional_predecessor_skips_optional_descendant():
    tasks=(Task(0, ()),
           Task(1, (0,), criticality='optional'),
           Task(2, (1,), criticality='optional'),
           Task(3, (0,)))
    trace=tuple(Attempt(1., .99, 1.) for _ in range(4))
    w=Workload(tasks=tasks, attempts=(trace,)*4,
               permanent_draws=(1.,0.,1.,1.),outage_windows=(),seed=8,shape='custom')
    r=simulate(w,Scenario('optional_chain', failure_prob=0, permanent_prob=.5,
                         deadline_s=30), 'none', log_events=True)
    assert r.success and r.succeeded_tasks==2
    assert any(e['event']=='optional_task_skipped' and e['task']==2 for e in r.events)
    assert not any(e['event']=='attempt_start' and e['task']==2 for e in r.events)
    assert any(e['event']=='brief_delivered' and e['completeness']=='partial'
               for e in r.events)
