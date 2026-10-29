"""Independent CSV integrity and reproducibility checks for saved experiments."""
from __future__ import annotations
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from .model import generate_workload, scenario_catalog
from .simulator import simulate


def audit_directory(path: str | Path, verify_replay: bool = True) -> dict:
    folder = Path(path)
    manifest = json.loads((folder/'run_manifest.json').read_text(encoding='utf-8'))
    with (folder/'replicate_metrics.csv').open(newline='', encoding='utf-8') as f:
        records = list(csv.DictReader(f))
    expected_count = manifest['replicates'] * len(manifest['scenarios']) * len(manifest['policies'])
    if len(records) != expected_count:
        raise ValueError(f'Expected {expected_count} records, found {len(records)}')
    keys = [(r['seed'], r['scenario'], r['policy']) for r in records]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicated seed/scenario/policy records')
    for r in records:
        n = int(r['task_count'])
        calls = int(r['calls'])
        retries = int(r['retry_calls'])
        succeeded = int(r['succeeded_tasks'])
        if not (0 <= retries <= calls <= 4*n and 0 <= succeeded <= n):
            raise ValueError(f'Invalid counts in record: {r}')
        if r['success'] == 'True' and (succeeded != n or r['failure_reason']):
            raise ValueError('Successful workflow did not complete all tasks')
        if r['policy'] == 'none' and retries != 0:
            raise ValueError('No-retry policy issued retries')
        if float(r['elapsed_s']) - scenario_catalog()[r['scenario']].deadline_s > 1e-9:
            raise ValueError('Workflow elapsed time exceeds deadline')
        if r['scenario'] == 'perfect_control' and (r['success'] != 'True' or calls != n):
            raise ValueError('Perfect-control invariant violated')
    if verify_replay:
        # Exact replay of a deterministically chosen representative condition.
        first = records[0]
        seed = int(first['seed'])
        workload = generate_workload(seed, n_tasks=manifest['n_tasks'],shape=manifest['shape'])
        replay = simulate(workload, scenario_catalog()[first['scenario']], first['policy']).record()
        for key, value in replay.items():
            actual = first[key]
            if isinstance(value, bool):
                correct = str(value) == actual
            elif isinstance(value, float):
                correct = abs(value - float(actual)) < 1e-8
            else:
                correct = str(value) == actual
            if not correct:
                raise ValueError(f'Replay mismatch in {key}: expected {value!r}, got {actual!r}')
    return {'records':len(records), 'unique_combinations':len(set(keys)),
            'scenario_counts':dict(Counter(r['scenario'] for r in records)),
            'exact_replay':verify_replay, 'valid':True}


def main():
    parser=argparse.ArgumentParser(description='Check saved RetryBench outputs')
    parser.add_argument('--dir', default='results')
    args=parser.parse_args()
    print(json.dumps(audit_directory(args.dir), indent=2))


if __name__ == '__main__':
    main()
