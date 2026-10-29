"""Deterministic, reusable counterfactual workload traces for retry experiments.

The generator never uses live services. No LLM outputs, real customers, or
sensitive workflows are involved. Every policy sees the same exogenous trace.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import math
import random
from typing import Literal

Shape = Literal['chain', 'fanout', 'layered']


def derived_seed(*parts: object) -> int:
    key = '|'.join(map(str, parts)).encode('utf-8')
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), 'big')


@dataclass(frozen=True)
class Task:
    task_id: int
    predecessors: tuple[int, ...]
    # By default every task is mandatory.
    name: str = ''
    criticality: Literal['mandatory', 'optional'] = 'mandatory'
    evidence_gate: bool = False
    # A source task with a TTL is fresh only when the brief is delivered before
    # the interval following successful collection expires.
    freshness_ttl_s: float | None = None


@dataclass(frozen=True)
class Attempt:
    latency: float
    transient_draw: float
    backoff_jitter: float


@dataclass(frozen=True)
class Workload:
    tasks: tuple[Task, ...]
    attempts: tuple[tuple[Attempt, ...], ...]
    permanent_draws: tuple[float, ...]
    outage_windows: tuple[tuple[float, float], ...]
    seed: int
    shape: str

    def __post_init__(self) -> None:
        n = len(self.tasks)
        if n == 0 or len(self.attempts) != n or len(self.permanent_draws) != n:
            raise ValueError('Inconsistent workload dimensions')
        for i, task in enumerate(self.tasks):
            if task.task_id != i or any(p < 0 or p >= i for p in task.predecessors):
                raise ValueError('Tasks must be topologically sorted and acyclic')
            if not self.attempts[i]:
                raise ValueError('Every task requires one or more attempts')
            if task.criticality not in ('mandatory', 'optional'):
                raise ValueError('Unknown task criticality')
            if task.freshness_ttl_s is not None and task.freshness_ttl_s <= 0:
                raise ValueError('Freshness TTL must be strictly positive')
            if task.criticality == 'mandatory' and any(
                self.tasks[parent].criticality == 'optional' for parent in task.predecessors
            ):
                raise ValueError('Mandatory tasks cannot depend on optional tasks')


def generate_workload(seed: int, n_tasks: int = 12, shape: Shape = 'layered',
                      max_attempts: int = 4, median_latency: float = 1.25,
                      sigma: float = 0.5) -> Workload:
    if n_tasks < 4 or max_attempts < 1 or median_latency <= 0 or sigma < 0:
        raise ValueError('Invalid workload configuration')
    if shape not in ('chain', 'fanout', 'layered'):
        raise ValueError('Unknown DAG shape')
    rng = random.Random(derived_seed(seed, 'graph'))
    predecessors: list[tuple[int, ...]] = []
    if shape == 'chain':
        predecessors = [() if i == 0 else (i-1,) for i in range(n_tasks)]
    elif shape == 'fanout':
        predecessors = [()] + [(0,) for _ in range(1, n_tasks-1)] + [tuple(range(1, n_tasks-1))]
    else:
        # Layered fork/join DAG, with a single source and a single sink.
        layers: list[list[int]] = [[0]]
        internal = list(range(1, n_tasks - 1))
        for offset in range(0, len(internal), 3):
            layers.append(internal[offset:offset+3])
        layers.append([n_tasks - 1])
        predecessors = [() for _ in range(n_tasks)]
        for li in range(1, len(layers)):
            prev = layers[li - 1]
            for node in layers[li]:
                k = len(prev) if li == len(layers) - 1 else rng.randint(1, min(2, len(prev)))
                predecessors[node] = tuple(sorted(rng.sample(prev, k)))
        # Ensure every layer's nodes contribute to the final sink through
        # a downstream path: consecutive next-layer nodes cover all parents.
        for li in range(1, len(layers)-1):
            for prev_node in layers[li]:
                nxt = layers[li+1]
                if not any(prev_node in predecessors[node] for node in nxt):
                    node = nxt[prev_node % len(nxt)]
                    predecessors[node] = tuple(sorted(set(predecessors[node]) | {prev_node}))
    tasks = tuple(Task(i, predecessors[i]) for i in range(n_tasks))
    attempts = []
    permanent_draws = []
    for i in range(n_tasks):
        r = random.Random(derived_seed(seed, 'task', i))
        permanent_draws.append(r.random())
        trace = []
        for _ in range(max_attempts):
            latency = max(.05, min(12.0, r.lognormvariate(math.log(median_latency), sigma)))
            trace.append(Attempt(latency, r.random(), r.uniform(0.85, 1.15)))
        attempts.append(tuple(trace))
    outage_rng = random.Random(derived_seed(seed, 'outages'))
    first = 4.5 + 3.0 * outage_rng.random()
    second = 19.0 + 4.0 * outage_rng.random()
    outages = ((first, first + 6.5), (second, second + 3.0))
    return Workload(tasks, tuple(attempts), tuple(permanent_draws), outages, seed, shape)


@dataclass(frozen=True)
class Scenario:
    name: str
    failure_prob: float = 0.15
    permanent_prob: float = 0.0
    timeout_s: float = 4.0
    deadline_s: float = 30.0
    workers: int = 4
    provider_rps: float | None = None
    burst_tokens: float = 3.0
    use_outages: bool = False
    # If enabled, 429 responses include synthetic observable Retry-After seconds.
    advertise_retry_after: bool = False
    # When true, a shared-outage rejection is observed as a generic HTTP 5xx.
    # Its causal origin remains hidden from the retry policy.
    mask_outages: bool = False
    observable_cooldown_factor: float = 1.5
    adaptive_window_s: float = 6.0
    adaptive_threshold: int = 2
    adaptive_short_s: float = 0.35
    adaptive_long_s: float = 1.5

    def __post_init__(self) -> None:
        if not 0 <= self.failure_prob <= 1 or not 0 <= self.permanent_prob <= 1:
            raise ValueError('Failure probabilities must be in [0,1]')
        if (self.adaptive_window_s <= 0 or self.adaptive_threshold < 1 or
            self.adaptive_short_s <= 0 or self.adaptive_long_s <= 0):
            raise ValueError('Adaptive controller parameters must be positive')
        if self.observable_cooldown_factor <= 0:
            raise ValueError('Observable cooldown must be positive')
        if self.timeout_s <= 0 or self.deadline_s <= 0 or self.workers < 1:
            raise ValueError('Timeout, deadline and workers must be positive')
        if self.provider_rps is not None and (self.provider_rps <= 0 or self.burst_tokens <= 0):
            raise ValueError('Provider rate and burst tokens must be positive')


def scenario_catalog() -> dict[str, Scenario]:
    return {
        'perfect_control': Scenario('perfect_control', failure_prob=0.0, timeout_s=100.0, deadline_s=120.0),
        'iid_low': Scenario('iid_low', failure_prob=.05),
        'iid_medium': Scenario('iid_medium', failure_prob=.20),
        'iid_high': Scenario('iid_high', failure_prob=.35),
        'outage': Scenario('outage', failure_prob=.08, use_outages=True),
        'rate_limit': Scenario('rate_limit', failure_prob=.08, provider_rps=1.8, burst_tokens=2.0),
        'tight_deadline': Scenario('tight_deadline', failure_prob=.20, deadline_s=12.0),
        'generous_deadline': Scenario('generous_deadline', failure_prob=.20, deadline_s=55.0),
    }
