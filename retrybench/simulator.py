"""Discrete-event workflow executor, including concurrency and provider limits."""
from __future__ import annotations
from dataclasses import dataclass, field
import heapq
from .model import Workload, Scenario
from .policies import PolicyName, RetryContext, decide, POLICIES, SUPPORTED_POLICIES


@dataclass
class Result:
    seed: int
    shape: str
    scenario: str
    policy: str
    success: bool
    elapsed_s: float
    calls: int
    retry_calls: int
    succeeded_tasks: int
    task_count: int
    rate_limit_rejections: int
    transient_errors: int
    outage_errors: int
    timeouts: int
    permanent_errors: int
    failure_reason: str
    events: list[dict] = field(default_factory=list, repr=False)

    def record(self) -> dict:
        return {k: v for k, v in vars(self).items() if k != 'events'}


class TokenBucket:
    def __init__(self, capacity: float, rate: float):
        self.tokens = capacity
        self.capacity = capacity
        self.rate = rate
        self.last_t = 0.0

    def accept(self, now: float) -> bool:
        self.tokens = min(self.capacity, self.tokens + max(0., now - self.last_t) * self.rate)
        self.last_t = now
        if self.tokens + 1e-10 >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def retry_after_s(self) -> float:
        """Observable lower-bound wait until the next token (after a rejection)."""
        return max(0.0, (1.0 - self.tokens) / self.rate)


def _critical_chain(tasks: tuple, current: int, done: set[int]) -> int:
    """Longest remaining chain from current failure through descendants.

    This intentionally ignores future success/failure and observed task latencies.
    """
    successors: list[list[int]] = [[] for _ in tasks]
    for task in tasks:
        for p in task.predecessors:
            successors[p].append(task.task_id)
    memo: dict[int, int] = {}
    def depth(node: int) -> int:
        if node in memo:
            return memo[node]
        memo[node] = 1 + max((depth(x) for x in successors[node] if x not in done), default=0)
        return memo[node]
    return depth(current)


def simulate(workload: Workload, scenario: Scenario, policy: PolicyName,
             max_attempts: int = 4, log_events: bool = False) -> Result:
    if policy not in SUPPORTED_POLICIES:
        raise ValueError('Unknown policy')
    if max_attempts < 1 or any(len(trace) < max_attempts for trace in workload.attempts):
        raise ValueError('Workload must contain all allowed attempts')
    n = len(workload.tasks)
    deadline = scenario.deadline_s
    status = ['pending'] * n
    attempt_count = [0] * n
    done: set[int] = set()
    queue: list[tuple[float, int, str, int, str]] = []
    ready: list[int] = []
    clock = 0.0
    seq = 0
    busy = 0
    calls = 0
    retries = 0
    errors = {k: 0 for k in ('rate_limit', 'transient', 'outage', 'timeout', 'permanent')}
    events: list[dict] = []
    bucket = TokenBucket(scenario.burst_tokens, scenario.provider_rps) if scenario.provider_rps else None
    # A 429 hint becomes observable only after the failed request is returned.
    retry_hints: dict[int, float] = {}
    # Completed HTTP outcomes only; time-windowed and reset on every workflow run.
    observed_history: list[tuple[float, str]] = []
    optional_ids = {task.task_id for task in workload.tasks if task.criticality == 'optional'}
    required_ids = set(range(n)) - optional_ids

    def all_terminal() -> bool:
        return all(x in ('done', 'failed', 'skipped') for x in status)

    def resolve_dependencies(now: float) -> None:
        # A skipped optional task cannot support downstream optional work.
        # Validation forbids mandatory nodes from depending on optional ones.
        for nxt in workload.tasks:
            nt = nxt.task_id
            if status[nt] != 'pending':
                continue
            parents = [status[p] for p in nxt.predecessors]
            if any(x in ('failed', 'skipped') for x in parents):
                if nt not in optional_ids:
                    raise RuntimeError('Mandatory task depends on failed optional task')
                status[nt] = 'skipped'
                log(now, 'optional_task_skipped', nt, reason='failed_optional_predecessor')
            elif all(x == 'done' for x in parents):
                status[nt] = 'ready'
                heapq.heappush(ready, nt)

    def log(when: float, kind: str, task_id: int, **details: object) -> None:
        if log_events:
            events.append({'time_s': round(when, 6), 'event': kind, 'task': task_id, **details})

    def add_event(when: float, kind: str, task_id: int, error: str = '') -> None:
        nonlocal seq
        heapq.heappush(queue, (when, seq, kind, task_id, error))
        seq += 1

    for task in workload.tasks:
        if not task.predecessors:
            status[task.task_id] = 'ready'
            heapq.heappush(ready, task.task_id)

    def launch(now: float) -> None:
        nonlocal busy, calls, retries
        while busy < scenario.workers and ready and now < deadline:
            tid = heapq.heappop(ready)
            if status[tid] != 'ready':
                raise RuntimeError('Invalid ready queue state')
            idx = attempt_count[tid]
            attempt = workload.attempts[tid][idx]
            attempt_count[tid] += 1
            calls += 1
            if idx:
                retries += 1
            status[tid] = 'running'
            busy += 1
            # Order of precedence: client-side provider throttle, known
            # non-retryable failure, outage at initiation, local timeout, 5xx.
            if bucket is not None and not bucket.accept(now):
                error = 'rate_limit'
                latency = 0.08
                if scenario.advertise_retry_after:
                    retry_hints[tid] = max(0., bucket.retry_after_s() - latency)
            elif workload.permanent_draws[tid] < scenario.permanent_prob:
                error = 'permanent'
                latency = min(0.18, attempt.latency)
            elif scenario.use_outages and any(a <= now < b for a, b in workload.outage_windows):
                error = 'outage'
                latency = 0.2
            elif attempt.latency >= scenario.timeout_s:
                error = 'timeout'
                latency = scenario.timeout_s
            elif attempt.transient_draw < scenario.failure_prob:
                error = 'transient'
                latency = attempt.latency
            else:
                error = ''
                latency = attempt.latency
            log(now, 'attempt_start', tid, attempt=idx+1,
                expected_response=error or 'success')
            add_event(now + latency, 'finish', tid, error)

    launch(clock)
    finished = False
    failure_reason = ''
    end_time = deadline
    while queue:
        when, _, kind, tid, error = heapq.heappop(queue)
        if when > deadline:
            break
        clock = when
        if kind == 'retry_ready':
            if status[tid] != 'retry_wait':
                raise RuntimeError('Retry readiness mismatch')
            status[tid] = 'ready'
            heapq.heappush(ready, tid)
            log(clock, 'retry_ready', tid)
            launch(clock)
            continue
        if status[tid] != 'running':
            raise RuntimeError('Completion state mismatch')
        busy -= 1
        if error:
            errors[error] += 1
            hint = retry_hints.pop(tid, None) if error == 'rate_limit' else None
            log(clock, 'attempt_failure', tid, error=error,
                attempt=attempt_count[tid], observed_error=('transient' if scenario.mask_outages and error == 'outage' else error),
                **({'retry_after_s': round(hint, 6)} if hint is not None else {}))
            observed_error = 'transient' if scenario.mask_outages and error == 'outage' else error
            observed_history.append((clock, observed_error))
            observed_history[:] = [(t, e) for t, e in observed_history
                                   if clock - t <= scenario.adaptive_window_s + 1e-9]
            recent_errors = sum(e in ('transient', 'timeout') for _, e in observed_history)
            current_trace = workload.attempts[tid][attempt_count[tid]-1]
            # Prevent an oracle leak: HTTP 5xx is observed, not its outage cause.
            observed_error = 'transient' if scenario.mask_outages and error == 'outage' else error
            ctx = RetryContext(error=observed_error, attempt_count=attempt_count[tid],
                               max_attempts=max_attempts, now=clock, deadline=deadline,
                               calls_so_far=calls, task_count=n,
                               longest_remaining_chain=_critical_chain(workload.tasks, tid, done),
                               jitter=current_trace.backoff_jitter,
                               retry_after_s=hint,
                               observable_cooldown_factor=scenario.observable_cooldown_factor,
                               recent_errors=recent_errors, recent_total=len(observed_history),
                               adaptive_threshold=scenario.adaptive_threshold,
                               adaptive_short_s=scenario.adaptive_short_s,
                               adaptive_long_s=scenario.adaptive_long_s)
            decision = decide(policy, ctx)
            if decision.retry and clock + decision.delay_s < deadline:
                status[tid] = 'retry_wait'
                add_event(clock + decision.delay_s, 'retry_ready', tid)
                log(clock, 'retry_scheduled', tid, delay_s=round(decision.delay_s, 6),
                    reason=decision.reason)
            else:
                status[tid] = 'failed'
                reason = decision.reason if not decision.retry else 'retry_after_deadline'
                if tid not in optional_ids:
                    failure_reason = reason
                    end_time = clock
                    log(clock, 'workflow_failure', tid, reason=failure_reason)
                    finished = True
                    break
                log(clock, 'optional_task_failure', tid, reason=reason)
                resolve_dependencies(clock)
        else:
            status[tid] = 'done'
            done.add(tid)
            observed_history.append((clock, 'success'))
            observed_history[:] = [(t, e) for t, e in observed_history
                                   if clock - t <= scenario.adaptive_window_s + 1e-9]
            log(clock, 'task_success', tid, attempt=attempt_count[tid])
            if len(done) == n:
                end_time = clock
                finished = True
                log(clock, 'workflow_success', tid)
                break
            resolve_dependencies(clock)
        if optional_ids and all_terminal():
            end_time = clock
            finished = True
            if required_ids.issubset(done):
                log(clock, 'brief_delivered', tid,
                    completeness='full' if len(done) == n else 'partial')
            else:
                failure_reason = 'mandatory_tasks_incomplete'
                log(clock, 'workflow_failure', tid, reason=failure_reason)
            break
        launch(clock)
    if not finished:
        end_time = deadline
        if optional_ids and required_ids.issubset(done):
            # Optional requests are incomplete at deadline, but mandatory
            # evidence gates have completed; deliver a labelled partial brief.
            log(end_time, 'brief_delivered', -1, completeness='partial')
        else:
            failure_reason = 'deadline_expired'
            log(end_time, 'workflow_failure', -1, reason=failure_reason)
    return Result(seed=workload.seed, shape=workload.shape, scenario=scenario.name,
                  policy=policy, success=(failure_reason == ''), elapsed_s=end_time,
                  calls=calls, retry_calls=retries, succeeded_tasks=len(done),
                  task_count=n, rate_limit_rejections=errors['rate_limit'],
                  transient_errors=errors['transient'], outage_errors=errors['outage'],
                  timeouts=errors['timeout'], permanent_errors=errors['permanent'],
                  failure_reason=failure_reason, events=events)
