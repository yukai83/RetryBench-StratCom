"""Synthetic strategic-communications *support* workflow templates and diagnostics.

No real-world information, influence targeting, human judgement or assertion
correctness is generated. 'Evidence complete' means all modelled check tasks ran
successfully, NOT that any factual claim was established as true.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from statistics import mean
import csv
import json
from .model import Task, Workload, Scenario, generate_workload
from .policies import PolicyName, POLICIES
from .simulator import Result, simulate

@dataclass(frozen=True)
class Step:
    name: str
    predecessors: tuple[int, ...] = ()
    criticality: str = 'mandatory'
    evidence_gate: bool = False
    freshness_ttl_s: float | None = None


# These are *synthetic tool calls*, not organizational SOPs or proof of verification.
TEMPLATES: dict[str, tuple[Step, ...]] = {
    'information_environment_assessment': (
        Step('retrieve_public_feed', freshness_ttl_s=24),
        Step('retrieve_official_bulletins', freshness_ttl_s=35),
        Step('normalise_and_deduplicate', (0, 1)),
        Step('extract_observed_topics', (2,)),
        Step('check_source_provenance', (2,), evidence_gate=True),
        Step('cross_check_factual_claims', (0, 1), evidence_gate=True),
        Step('optional_context_enrichment', (3,), 'optional'),
        Step('optional_visualisation', (3,), 'optional'),
        Step('prepare_evidence_log', (3, 4, 5)),
        Step('queue_human_review', (8,)),
    ),
    'live_fact_check_support': (
        Step('capture_public_claim', freshness_ttl_s=20),
        Step('retrieve_official_records', (0,), freshness_ttl_s=30),
        Step('retrieve_independent_sources', (0,), freshness_ttl_s=24),
        Step('check_citation_provenance', (1, 2), evidence_gate=True),
        Step('check_cross_source_consistency', (3,), evidence_gate=True),
        Step('optional_context_lookup', (2,), 'optional'),
        Step('draft_evidence_annotated_note', (4,)),
        Step('queue_human_review', (6,)),
    ),
    'communications_situation_report': (
        Step('retrieve_public_updates', freshness_ttl_s=24),
        Step('retrieve_official_updates', freshness_ttl_s=35),
        Step('retrieve_event_timeline', freshness_ttl_s=32),
        Step('align_timestamps', (0, 1, 2)),
        Step('check_provenance', (0, 1), evidence_gate=True),
        Step('check_timeline_consistency', (3, 4), evidence_gate=True),
        Step('optional_background_context', (3,), 'optional'),
        Step('prepare_situation_summary', (3, 5)),
        Step('queue_human_review', (7,)),
    ),
}


def make_assessment_workload(seed: int, template: str = 'information_environment_assessment',
                             max_attempts: int = 4, median_latency: float = 1.25,
                             sigma: float = .5) -> Workload:
    """Create fixed, pairable task/attempt traces from the existing generator."""
    if template not in TEMPLATES:
        raise ValueError(f'Unknown StratCom template: {template}')
    steps = TEMPLATES[template]
    base = generate_workload(seed, n_tasks=len(steps), shape='layered',
                             max_attempts=max_attempts, median_latency=median_latency,
                             sigma=sigma)
    tasks = tuple(Task(i, x.predecessors, x.name, x.criticality,
                       x.evidence_gate, x.freshness_ttl_s)
                  for i, x in enumerate(steps))
    return Workload(tasks, base.attempts, base.permanent_draws,
                    base.outage_windows, seed, f'stratcom:{template}')


@dataclass(frozen=True)
class BriefMetrics:
    seed: int
    template: str
    scenario: str
    policy: str
    status: str
    brief_delivered: bool
    all_tasks_completed: bool
    mandatory_tasks_completed: bool
    evidence_checks_completed: bool
    mandatory_sources_fresh: bool
    timely_evidence_complete: bool
    freshness_max_age_s: float | None
    mandatory_task_count: int
    optional_task_count: int
    optional_completed: int
    optional_missing: int
    deadline_s: float
    elapsed_s: float
    calls: int
    retries: int
    failure_reason: str

    def record(self) -> dict:
        return asdict(self)


def assess_result(workload: Workload, scenario: Scenario, result: Result) -> BriefMetrics:
    """Audit trace-backed procedural completeness and source freshness.

    A successful `check_*` task represents a synthetic tool-call success only;
    it cannot validate whether its hypothetical content is accurate.
    """
    if not result.events:
        raise ValueError('Assessment metrics require log_events=True')
    done_at = {e['task']: e['time_s'] for e in result.events
               if e['event'] == 'task_success'}
    required = [t for t in workload.tasks if t.criticality == 'mandatory']
    optional = [t for t in workload.tasks if t.criticality == 'optional']
    mandatory_ok = all(t.task_id in done_at for t in required)
    checks_ok = all(t.task_id in done_at for t in required if t.evidence_gate)
    sources = [t for t in required if t.freshness_ttl_s is not None]
    source_ages = [result.elapsed_s - done_at[t.task_id] for t in sources
                   if t.task_id in done_at]
    source_fresh = bool(sources) and all(
        t.task_id in done_at and
        # Avoid rounding-induced borderline false positives/negatives.
        result.elapsed_s - done_at[t.task_id] <= t.freshness_ttl_s + 1e-6
        for t in sources)
    optional_done = sum(t.task_id in done_at for t in optional)
    delivered = result.success and mandatory_ok
    status = ('failed' if not delivered else
              'full' if optional_done == len(optional) else 'partial')
    return BriefMetrics(
        seed=workload.seed, template=workload.shape.split(':', 1)[-1],
        scenario=scenario.name, policy=result.policy, status=status,
        brief_delivered=delivered,
        all_tasks_completed=delivered and optional_done == len(optional),
        mandatory_tasks_completed=mandatory_ok, evidence_checks_completed=checks_ok,
        mandatory_sources_fresh=source_fresh,
        timely_evidence_complete=(delivered and checks_ok and source_fresh and
                                  result.elapsed_s <= scenario.deadline_s),
        freshness_max_age_s=max(source_ages) if source_ages else None,
        mandatory_task_count=len(required), optional_task_count=len(optional),
        optional_completed=optional_done, optional_missing=len(optional)-optional_done,
        deadline_s=scenario.deadline_s, elapsed_s=result.elapsed_s,
        calls=result.calls, retries=result.retry_calls,
        failure_reason=result.failure_reason)


def simulate_assessment(workload: Workload, scenario: Scenario,
                        policy: PolicyName, max_attempts: int = 4,
                        log_events: bool = False) -> tuple[BriefMetrics, Result]:
    if not workload.shape.startswith('stratcom:'):
        raise ValueError('A StratCom workflow is required')
    raw = simulate(workload, scenario, policy, max_attempts=max_attempts, log_events=True)
    metrics = assess_result(workload, scenario, raw)
    if not log_events:
        raw.events = []
    return metrics, raw


def run_assessment_study(output_dir: str | Path, replicates: int = 10,
                         seed: int = 2026, template: str = 'information_environment_assessment',
                         scenarios: tuple[Scenario, ...] | None = None) -> list[dict]:
    """Optional smoke study, not a calibrated or definitive experiment."""
    if replicates < 1:
        raise ValueError('replicates must be positive')
    if scenarios is None:
        scenarios = (
            Scenario('stratcom_iid', failure_prob=.2, deadline_s=30),
            Scenario('stratcom_tight', failure_prob=.2, deadline_s=12),
            Scenario('stratcom_rate_limit_with_hint', failure_prob=.08,
                     provider_rps=1.8, burst_tokens=2., deadline_s=40,
                     advertise_retry_after=True),
        )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for rep in range(replicates):
        workload = make_assessment_workload(seed + rep, template)
        for scenario in scenarios:
            for policy in POLICIES:
                metrics, _ = simulate_assessment(workload, scenario, policy)
                rows.append(metrics.record())
    with (output / 'stratcom_replicate_metrics.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = []
    for sc in scenarios:
        for policy in POLICIES:
            sub = [r for r in rows if r['scenario'] == sc.name and r['policy'] == policy]
            summary.append({'scenario': sc.name, 'policy': policy, 'n': len(sub),
                            'brief_delivery_rate': mean(r['brief_delivered'] for r in sub),
                            'timely_evidence_complete_rate': mean(r['timely_evidence_complete'] for r in sub),
                            'partial_delivery_rate': mean(r['status'] == 'partial' for r in sub),
                            'fresh_source_rate': mean(r['mandatory_sources_fresh'] for r in sub),
                            'mean_calls': mean(r['calls'] for r in sub)})
    with (output / 'stratcom_condition_summary.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    (output / 'stratcom_manifest.json').write_text(json.dumps({
        'study_status': 'engineering smoke test; not publishable claims',
        'replicates': replicates, 'seed': seed, 'template': template,
        'policies': list(POLICIES), 'scenarios': [asdict(s) for s in scenarios],
        'source_accuracy': 'Not represented; source freshness uses time only',
        'evidence_checks_completed': 'Success of synthetic checking tasks; NOT actual fact verification',
        'human_review': 'Handoff task only, NOT human approval',
        'limitation': 'One workflow owns the rate limiter; no cross-tenant traffic',
    }, indent=2), encoding='utf-8')
    return summary
