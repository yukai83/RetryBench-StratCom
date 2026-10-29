"""Paired Monte Carlo experiment with transparent, seeded uncertainty estimates."""
from __future__ import annotations
import csv
import json
import random
from pathlib import Path
from statistics import mean
from .model import derived_seed, generate_workload, scenario_catalog
from .policies import POLICIES
from .simulator import simulate

FIELDS = ('success', 'elapsed_s', 'calls', 'retry_calls', 'rate_limit_rejections')


def summarize(rows: list[dict]) -> list[dict]:
    output = []
    keys = sorted(set((r['scenario'], r['policy']) for r in rows))
    for scenario, policy in keys:
        subset = [r for r in rows if r['scenario'] == scenario and r['policy'] == policy]
        d = {'scenario': scenario, 'policy': policy, 'n': len(subset)}
        for field in FIELDS:
            d['mean_' + field] = mean(float(r[field]) for r in subset)
        successful = [float(r['elapsed_s']) for r in subset if r['success']]
        d['mean_latency_success_only_s'] = mean(successful) if successful else None
        # Nearest-rank p95 conditional on successful completions (>=10 successes).
        d['p95_latency_success_only_s'] = (sorted(successful)[min(len(successful)-1, __import__('math').ceil(.95*len(successful))-1)]
                                              if len(successful) >= 10 else None)
        output.append(d)
    return output


def paired_contrasts(rows: list[dict], n_boot: int = 1000) -> list[dict]:
    """Matched-seed contrasts; positive estimates mean first policy > second."""
    if n_boot < 40:
        raise ValueError('n_boot should be at least 40')
    by_key = {(r['scenario'], r['seed'], r['policy']): r for r in rows}
    scenarios = sorted(set(r['scenario'] for r in rows))
    comparisons = [(policy, 'none') for policy in POLICIES if policy != 'none']
    comparisons += [('exponential', 'immediate'), ('budget_aware', 'immediate'),
                    ('budget_aware', 'exponential')]
    out = []
    for scenario in scenarios:
        seeds = sorted(set(r['seed'] for r in rows if r['scenario'] == scenario))
        for first, second in comparisons:
            for field in FIELDS:
                diffs = [float(by_key[(scenario, seed, first)][field]) -
                         float(by_key[(scenario, seed, second)][field]) for seed in seeds]
                estimate = mean(diffs)
                rng = random.Random(derived_seed('bootstrap', scenario, first, second, field))
                boot = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs)
                              for _ in range(n_boot))
                lo = boot[int(.025 * n_boot)]
                hi = boot[min(n_boot - 1, int(.975 * n_boot))]
                out.append({'scenario': scenario, 'first_policy': first,
                            'second_policy': second, 'metric': field,
                            'n_pairs': len(diffs), 'mean_difference': estimate,
                            'bootstrap_ci95_low': lo, 'bootstrap_ci95_high': hi})
    return out


def write_csv(path: Path, records: list[dict]) -> None:
    if not records:
        return
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def run_study(output_dir: str | Path, replicates: int = 40, seed: int = 2026,
              n_tasks: int = 12, shape: str = 'layered',
              scenarios: list[str] | None = None,
              make_plots: bool = True) -> tuple[list[dict], list[dict]]:
    if replicates < 2:
        raise ValueError('At least two matched replicates required')
    catalog = scenario_catalog()
    selected = scenarios or list(catalog)
    if any(s not in catalog for s in selected):
        raise ValueError('Unknown scenario; choose from: ' + ', '.join(catalog))
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    data = []
    for i in range(replicates):
        trial_seed = seed + i
        workload = generate_workload(trial_seed, n_tasks=n_tasks, shape=shape)
        for scenario_name in selected:
            scenario = catalog[scenario_name]
            for policy in POLICIES:
                data.append(simulate(workload, scenario, policy).record())
    means = summarize(data)
    intervals = paired_contrasts(data)
    write_csv(outdir / 'replicate_metrics.csv', data)
    write_csv(outdir / 'condition_summary.csv', means)
    write_csv(outdir / 'paired_bootstrap_95ci.csv', intervals)
    manifest = {
        'design': 'paired discrete-event simulation; synthetic traces',
        'replicates': replicates, 'seed': seed, 'n_tasks': n_tasks,
        'shape': shape, 'scenarios': selected, 'policies': list(POLICIES),
        'estimands': {
            'success': 'fraction of workflows completing all DAG tasks by deadline',
            'elapsed_s': 'time-to-workflow termination, censored at scenario deadline',
            'calls': 'all tool call attempts including rejected/failed attempts',
            'retry_calls': 'attempts with index >=2',
            'rate_limit_rejections': 'attempts rejected by simulated token bucket',
            'mean_latency_success_only_s': 'conditional mean among successes; selection bias possible',
            'p95_latency_success_only_s': 'nearest rank p95 among successes; omitted when fewer than 10 successes',
            'paired_difference': 'per-seed policy minus no-retry mean with percentile bootstrap',
        },
        'disclaimer': 'Exclusively synthetic; no LLM performance or provider measurements.'
    }
    (outdir / 'run_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    if make_plots:
        from .plotting import create_figures
        create_figures(means, outdir)
    return data, means
