"""Retry strategies with a common maximum attempts per task.

Decision-making uses only observed failure labels, time, attempts used,
known DAG structure, and the task's *assumed* median latency. No future
error draws or outage windows are exposed to policies.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

PolicyName = Literal['none', 'immediate', 'exponential', 'budget_aware']
POLICIES: tuple[PolicyName, ...] = ('none', 'immediate', 'exponential', 'budget_aware')
# Experiment-only variants: cooldown components, observable baselines and the history controller.
ABLATION_POLICIES = ('cooldown_only', 'cooldown_call_cap', 'cooldown_deadline_guard', 'observable_cooldown', 'history_adaptive', 'sdk_style_proxy')
SUPPORTED_POLICIES = POLICIES + ABLATION_POLICIES


@dataclass(frozen=True)
class RetryContext:
    error: str
    attempt_count: int
    max_attempts: int
    now: float
    deadline: float
    calls_so_far: int
    task_count: int
    longest_remaining_chain: int
    jitter: float
    retry_after_s: float | None = None
    observable_cooldown_factor: float = 1.5
    recent_errors: int = 0
    recent_total: int = 0
    adaptive_threshold: int = 2
    adaptive_short_s: float = 0.35
    adaptive_long_s: float = 1.5


@dataclass(frozen=True)
class Decision:
    retry: bool
    delay_s: float = 0.0
    reason: str = ''


def decide(policy: PolicyName, context: RetryContext) -> Decision:
    if policy not in SUPPORTED_POLICIES:
        raise ValueError(f'Unknown retry policy: {policy}')
    if context.error == 'permanent':
        return Decision(False, reason='non_retryable_error')
    if context.attempt_count >= context.max_attempts:
        return Decision(False, reason='attempt_limit')
    if context.now >= context.deadline:
        return Decision(False, reason='deadline_expired')
    if policy == 'none':
        return Decision(False, reason='no_retry_policy')
    if policy == 'immediate':
        return Decision(True, delay_s=0.0, reason='immediate')
    if policy in ('exponential', 'sdk_style_proxy'):
        if policy == 'sdk_style_proxy' and context.calls_so_far >= int(context.task_count * 1.8 + 0.5):
            return Decision(False, reason='sdk_style_retry_quota')
        delay = min(8., 0.8 * (2 ** (context.attempt_count - 1))) * context.jitter
        if context.error == 'rate_limit' and context.retry_after_s is not None:
            delay = max(delay, context.retry_after_s)
        return Decision(True, delay_s=delay, reason='backoff')
    if policy == 'history_adaptive':
        # Observed codes, recent completed responses and Retry-After only.
        # No future outcomes, underlying outage label, or historical data from other trials.
        high = context.recent_errors >= context.adaptive_threshold
        if context.error == 'rate_limit':
            delay = max(0.8 * context.attempt_count, context.retry_after_s or 0.)
        elif context.error in ('transient', 'timeout', 'outage'):
            scale = context.adaptive_long_s if high else context.adaptive_short_s
            delay = min(5., scale * context.attempt_count * context.jitter)
        else:
            return Decision(False, reason='non_retryable_error')
        # Do not schedule a retry when it cannot plausibly return before deadline.
        # This is a simple observable slack guard, not a learned optimal scheduler.
        if context.now + delay + 0.10 >= context.deadline:
            return Decision(False, reason='insufficient_response_slack')
        return Decision(True, delay_s=delay, reason='observable_history')
    # Budget-aware and controlled ablations use identical error-aware cooldown.
    # observable_cooldown cannot see hidden outage causes: it applies a
    # conservative delay to observable transient 5xx responses.
    # The ablations separate the call-cap and forecast-based deadline guard.
    max_workflow_calls = int(context.task_count * 1.8 + .5)
    if policy in ('budget_aware', 'cooldown_call_cap') and context.calls_so_far >= max_workflow_calls:
        return Decision(False, reason='workflow_call_budget')
    if context.error == 'rate_limit':
        delay = min(4., 1.5 * context.attempt_count) * context.jitter
    elif context.error == 'outage' or (policy == 'observable_cooldown' and context.error == 'transient'):
        delay = min(5., (context.observable_cooldown_factor if policy == 'observable_cooldown' else 1.5) * context.attempt_count) * context.jitter
    else:
        delay = 0.2 * context.attempt_count * context.jitter
    if context.error == 'rate_limit' and context.retry_after_s is not None:
        delay = max(delay, context.retry_after_s)
    # Conservative critical-path lower-bound estimate, intentionally learned
    # from design assumptions rather than hidden future task latencies.
    expected_remaining = context.longest_remaining_chain * 1.25
    if policy in ('budget_aware', 'cooldown_deadline_guard') and context.now + delay + expected_remaining > context.deadline:
        return Decision(False, reason='insufficient_time_slack')
    return Decision(True, delay_s=delay, reason=policy)
