# RetryBench–StratCom

Code, results and paper sources for *When Does Waiting Help? Observable-History Retry Control for API-Dependent Agentic AI Workflows* (five-page IEEE conference paper, prepared for ICNGN 2026).

**Repository:** https://github.com/yukai83/RetryBench-StratCom

**Status:** synthetic research prototype. It is not operational guidance or field validation, and it implies no institutional endorsement.

## What the study does

A seeded discrete-event simulator runs three strategic-communications reporting workflows and five retry policies under injected faults. The study has five parts:

1. **Label-masking control** (Table I). The same outages are shown to a policy either with their cause visible or as a generic 5xx.
2. **Main study** (Tables II–III). A three-parameter observable-history controller is tuned on development seeds and frozen. It is then compared with four baselines on held-out conditions, unseen graph shapes and real localhost HTTP requests (Section V-G).
3. **Post-hoc diagnostics** (Figs. 1–2 and Section V). These cover an outage-length sweep, a history-window sweep, a detector check scored against the hidden outage label, a switching ablation (the controller against its own two waits used alone and against perfect detection, an upper bound that reads the hidden label), a wider tuning grid, a deadline-guard ablation and how often the proxy's call cap binds. Added in the camera-ready revision: a threshold sweep over `k`, `β_long` and a circuit-breaker-style failure-rate rule (Fig. 1), every development-grid setting rerun on the held-out cells, and the controller-versus-baseline contrast pooled over all fifteen held-out cells.
4. **Load-coupled outages** (Table IV, Section V-E; added in the revision). Every request received during an outage postpones its end by `δ` seconds, so retries can prolong outages. `δ = 0` reproduces the scheduled-outage records exactly. The Table I label-masking control is rerun at each `δ`.
5. **Checks.** An audit script reconciles every saved result. A verification script recomputes every number quoted in the paper's text from the data and the code.

## Reproduce

Requires Python ≥ 3.10 with `numpy`, `matplotlib` and `pytest`; `pdflatex` with IEEEtran for the paper; `pandoc` and `python-docx` for the optional Word copy.

```bash
python -m pip install -e '.[test,study]'
python -m pytest -q                  # 98 tests
python run_label_masking.py          # Table I                  -> results/label_masking/
python run_main_study.py             # tuning, freeze, held-out -> results/main/
python run_window_sweep.py           # Section V-E              -> results/main/
python local_http_benchmark.py       # Section V-G, real sockets -> results/main/
python run_diagnostics.py            # Figs. 1-2, Section V     -> results/diagnostics/
python run_load_coupling.py          # Table IV, Section V-E    -> results/load_coupling/
python audit_results.py              # reconciliation           -> results/audit.json
python make_tables.py && python make_figures.py
python verify_paper_numbers.py       # every number in the text vs. the data and the code
pdflatex main.tex && pdflatex main.tex
python build_word.py                 # optional editable Word copy (run after pdflatex)
```

Simulated results are deterministic for a given Python version. The localhost HTTP timings vary with OS scheduling, but the outcomes do not.

## Policy names: paper vs. code

| Paper | Code |
|---|---|
| Immediate | `immediate` |
| Exponential backoff | `exponential` |
| SDK-style proxy (not an AWS SDK) | `sdk_style_proxy` |
| Linear cooldown | `observable_cooldown` |
| History-adaptive | `history_adaptive` |
| Cause-aware (Table I only; reads the outage label when it is visible) | `budget_aware` |

## Conditions

All held-out, development and sweep conditions mask outages as a generic 5xx. Background errors are IID per attempt.

| Use | Condition | Deadline | Background errors | Other |
|---|---|---|---|---|
| Label-masking (Table I) | `outage_45` | 45 s | 8% | unextended outages, label visible or masked |
| Development | `dev_iid` | 22 s | 22% | |
| Development | `dev_outage` | 45 s | 7% | unextended outages |
| Development | `dev_quota` | 55 s | 8% | hinted quota 1.8 req/s, burst 2 |
| Held-out | `held_iid_27` | 26 s | 27% | |
| Held-out | `held_outage_extended` | 48 s | 10% | both outage windows +2 s |
| Held-out | `held_tight_17` | 14 s | 17% | |
| Held-out | `held_quota_23` | 52 s | 9% | hinted quota 2.3 req/s, burst 2 |
| Held-out | `held_mixed` | 40 s | 20% | plus 2% permanent errors |
| Unseen graphs | `newgraph_iid` / `newgraph_outage` | 50 s / 55 s | 23% / 10% | outage windows unextended |
| Load-coupled (post hoc) | `held_outage_extended` with `outage_load_delay_s` = δ | 48 s | 10% | windows +0 s or +2 s; δ ∈ {0, 0.1, 0.2, 0.3, 0.5, 1} s |

Outage windows: 6.5 s starting at 4.5–7.5 s and 3.0 s starting at 19–23 s (per seed). The history window `W` = 6 s was set before tuning, just under the first outage window. That is a simulator-informed choice a deployed client could not make; `run_window_sweep.py` tests 2 and 12 s, and Section V-F of the paper describes calibrating `W` and `k` from a client's own logs.

## Seed ranges (disjoint)

| Use | Seeds |
|---|---|
| Label-masking control | 2026–2225 |
| Development grid | 61100–61139 |
| Held-out workflows, sweeps, detector | 91000–91199 |
| Unseen generic DAGs | 140000–140119 |
| Localhost HTTP | 221000–221015 |

## Files

- `main.tex`, `main.pdf`, `tables/`, `figures/`: the paper. Tables and figures are generated by `make_tables.py` and `make_figures.py`, and Table III's caption reads its deadlines and error rates from the scenario definitions. Three generated items left the paper in the camera-ready revision to meet the five-page limit and stay in the repository as supplementary material: the IEA workflow diagram (`figures/workflow_structure.pdf`, drawn from `retrybench/stratcom.py`), the paired-interval figure (`figures/heldout_differences.pdf`) and the per-workflow switching-ablation table (`tables/switching.tex`). `RetryBench_StratCom_Editable_Two_Column.docx` is an editable working copy, not a byte-exact IEEEtran replica. Its equations render in Microsoft Word, but some other viewers leave inline math blank.
- `retrybench/`: simulator, workflows, scenarios and retry policies. `tests/`: unit and regression tests.
- `results/label_masking/`, `results/main/`, `results/diagnostics/`, `results/load_coupling/`: per-seed CSVs, summaries, the frozen configuration (`results/main/frozen_parameters.json`) and manifests.
- `REVISION.md`: what changed for the camera-ready version and how each reviewer comment was addressed.
- `results/audit.json`: output of `audit_results.py`.

## Boundaries

The workflows are synthetic toy information-assessment procedures, not data from any organisational system. A successful checking task shows only that a simulated tool call ran; it does not show a claim is true. Outages start on a schedule. `run_load_coupling.py` lets requests sent during an outage prolong it, but each trial has one workflow and no queueing, so self-sustaining (metastable) overload is not modelled. Do not apply retries to side-effecting tools without idempotency protection.
