"""Matplotlib is optional; separate categorical bar charts for publication."""
from pathlib import Path
from .policies import POLICIES


def create_figures(summary: list[dict], outdir: str | Path) -> None:
    import matplotlib.pyplot as plt
    import math
    path = Path(outdir)
    scenarios = ['perfect_control','iid_low','iid_medium','iid_high','outage',
                 'rate_limit','tight_deadline','generous_deadline']
    scenarios = [s for s in scenarios if any(r['scenario']==s for r in summary)]
    # Include any custom scenarios after the fixed conceptual order.
    scenarios += sorted(set(r['scenario'] for r in summary)-set(scenarios))
    labels = {'none': 'No retry', 'immediate': 'Immediate',
              'exponential': 'Exp. backoff', 'budget_aware': 'Budget-aware'}
    metrics = [('mean_success','Completion probability by deadline'),
               ('mean_calls','Mean tool-call attempts'),
               ('mean_elapsed_s','Mean time to terminal state (s)'),
               ('mean_latency_success_only_s','Mean completion time among successes (s)')]
    for field, ylabel in metrics:
        fig, ax = plt.subplots(figsize=(11.7, 4.7))
        w = .18
        for i, policy in enumerate(POLICIES):
            lookup = {r['scenario']:r[field] for r in summary if r['policy']==policy}
            vals = [math.nan if lookup[x] is None else lookup[x] for x in scenarios]
            ax.bar([j + (i-1.5)*w for j in range(len(scenarios))], vals,
                   width=w, label=labels[policy])
        ax.set_xticks(range(len(scenarios)), [s.replace('_',' ') for s in scenarios],
                      rotation=22, ha='right')
        ax.set_ylabel(ylabel)
        if field == 'mean_success':
            ax.set_ylim(0, 1.08)
        ax.grid(axis='y', alpha=.2)
        ax.set_axisbelow(True)
        ax.legend(ncol=4, loc='upper center', fontsize=8)
        fig.tight_layout()
        fig.savefig(path / f'{field}.png', dpi=190)
        fig.savefig(path / f'{field}.pdf')
        plt.close(fig)
