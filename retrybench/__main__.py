from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from .model import generate_workload, scenario_catalog
from .policies import POLICIES
from .simulator import simulate
from .experiment import run_study
from .stratcom import TEMPLATES, make_assessment_workload, simulate_assessment, run_assessment_study


def main() -> None:
    parser = argparse.ArgumentParser(description='Synthetic tool-calling AI workflow retry simulator')
    sub = parser.add_subparsers(dest='command', required=True)
    study = sub.add_parser('run', help='Run matched-seed experiment suite')
    study.add_argument('--replicates', type=int, default=40)
    study.add_argument('--seed', type=int, default=2026)
    study.add_argument('--tasks', type=int, default=12)
    study.add_argument('--shape', choices=['chain','fanout','layered'], default='layered')
    study.add_argument('--scenarios', nargs='*', choices=list(scenario_catalog()))
    study.add_argument('--out', default='results')
    study.add_argument('--no-plots', action='store_true')
    demo = sub.add_parser('demo', help='Run a single trace, optionally export event log')
    demo.add_argument('--seed', type=int, default=42)
    demo.add_argument('--scenario', choices=list(scenario_catalog()), default='outage')
    demo.add_argument('--policy', choices=POLICIES, default='exponential')
    demo.add_argument('--shape', choices=['chain','fanout','layered'], default='layered')
    demo.add_argument('--tasks', type=int, default=12)
    demo.add_argument('--events', default='demo_events.csv')
    sc_demo = sub.add_parser('stratcom-demo', help='Synthetic StratCom trace and procedural completeness metrics')
    sc_demo.add_argument('--seed', type=int, default=42)
    sc_demo.add_argument('--template', choices=sorted(TEMPLATES), default='information_environment_assessment')
    sc_demo.add_argument('--scenario', choices=list(scenario_catalog()), default='iid_medium')
    sc_demo.add_argument('--policy', choices=POLICIES, default='budget_aware')
    sc_demo.add_argument('--events', default='stratcom_demo_events.csv')
    sc_run = sub.add_parser('stratcom-run', help='Small paired smoke study of the StratCom workflows')
    sc_run.add_argument('--replicates', type=int, default=10)
    sc_run.add_argument('--seed', type=int, default=2026)
    sc_run.add_argument('--template', choices=sorted(TEMPLATES), default='information_environment_assessment')
    sc_run.add_argument('--out', default='stratcom_results')
    args = parser.parse_args()
    if args.command == 'run':
        _, rows = run_study(args.out, replicates=args.replicates, seed=args.seed,
                            n_tasks=args.tasks, shape=args.shape,
                            scenarios=args.scenarios, make_plots=not args.no_plots)
        print(f'Wrote {len(rows)} scenario/policy summaries to {args.out}')
        for row in rows:
            print(f"{row['scenario']:18} {row['policy']:14} "
                  f"success={row['mean_success']:.3f}  calls={row['mean_calls']:.2f}  "
                  f"end_time={row['mean_elapsed_s']:.2f}s")
    elif args.command == 'stratcom-run':
        summary = run_assessment_study(args.out, replicates=args.replicates,
                                       seed=args.seed, template=args.template)
        print(f'Wrote {len(summary)} condition summaries to {args.out}')
        print(json.dumps(summary, indent=2))
    elif args.command == 'stratcom-demo':
        work = make_assessment_workload(args.seed, args.template)
        metrics, result = simulate_assessment(work, scenario_catalog()[args.scenario],
                                             args.policy, log_events=True)
        outfile = Path(args.events)
        outfile.parent.mkdir(parents=True, exist_ok=True)
        keys = sorted(set().union(*(e.keys() for e in result.events)))
        with outfile.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(result.events)
        print(json.dumps(metrics.record(), indent=2))
        print('Event log:', outfile)
    elif args.command == 'demo':
        work = generate_workload(args.seed, args.tasks, args.shape)
        result = simulate(work, scenario_catalog()[args.scenario], args.policy, log_events=True)
        events_path = Path(args.events)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        keys = ['time_s','event','task','attempt','expected_response','error','reason','delay_s']
        with events_path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(result.events)
        print(json.dumps(result.record(), indent=2))
        print('Event log:', events_path)


if __name__ == '__main__':
    main()
