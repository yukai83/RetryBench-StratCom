# Camera-ready revision: ICNGN 2026, paper 253

*When Does Waiting Help? Observable-History Retry Control for API-Dependent Agentic AI Workflows*, by Yukai Zeng.

Both reviewers raised the same three points: outages scheduled in advance, the linear cooldown's slightly better average, and the 26% false-alarm rate. Reviewer 2 added three more: the scope of the HTTP test, the choice of `W`, and the SDK-style proxy. Each point is answered below with new evidence where we could produce it, and with clearer text where text was the right fix. Section numbers refer to the revised paper.

None of the new analyses changes the frozen controller or any primary result. All primary records reproduce byte-for-byte after the code changes. Every number added to the text is recomputed by `verify_paper_numbers.py`.

## Responses to the reviewers

### 1. Outages are pre-scheduled, so retries cannot prolong them (R1; R2 item 1)

**New experiment: Section V-F and Table IV (`run_load_coupling.py`).** Every request that reaches the service during an outage now delays the outage's end by δ seconds, for δ from 0 to 1 s. δ can also stand for retries from other clients. We ran this at the development outage length and at the primary +2-s length: 36,000 trials on the held-out seeds. We also reran the Table I label-masking control at each δ.

A workflow sent only 2.8–4.0 requests into an outage on average, because tasks queued behind a failed retrieval send nothing. Load therefore acted mainly as a longer outage. For example, δ = 0.3 s gave about 1 s more outage, and results close to the +1-s point of the outage-length sweep.

The paper now says explicitly which conclusions depend on the assumption.

- **Do not depend on it.**
  - The independent-fault and quota results have no outage windows.
  - The quota condition already has load feedback through its token bucket. Under it, the policies that honour `Retry-After` stayed at 98.0–100%.
  - The label-masking finding held: the visible-label policy stayed at least 34 points ahead of its masked runs at every δ.
  - The controller's gain over exponential backoff held at every δ and both lengths. The smallest gain was +3.5 points, CI 2.2–5.0.
- **Depends on it: the controller against the linear cooldown.**
  - At the development length, the controller's 6.0-point lead (CI 3.3–8.8) vanished at δ = 0.2 and reversed at δ ≥ 0.3 (−5.3, CI −9.0 to −1.5).
  - At the extended length, the cooldown's lead narrowed only as every policy fell towards immediate retry's level.
  - The paper states plainly that if retries prolong outages, the case for the controller over the cooldown is weaker.
- **Still not modelled (Section VI).** Each trial has one workflow and no queueing, so self-sustaining (metastable) overload cannot arise.

### 2. The linear cooldown is slightly better on average (R1; R2 item 2)

**Revised: Section V-A, the introduction's contributions paragraph, the abstract and the conclusion.**

- **The averages are a statistical tie.** Pooled over all fifteen held-out cells, the controller was 0.3 points behind the cooldown, with a seed-bootstrap 95% CI of −1.7 to +1.2.
- **The two policies fail in opposite places.**
  - The controller beat the cooldown in all twelve cells outside the extended outage, by 5.0 points on average.
  - Their worst shortfalls from a cell's best policy were almost the same: 26.5 points for the controller (LFC, outage) and 26.0 for the cooldown (LFC, tight deadlines).
- **The tie owes more to the frozen choice than to observable history.** The next two development-grid settings (k = 2, β_long = 1.5) scored 0.8 points lower on development data, which is three of 360 trials. On held-out data they would have matched or beaten the cooldown in 14 and 15 of the 15 cells. We report this only post hoc and keep the frozen setting (`devgrid_heldout.csv`).
- **The contribution claim is restated.** We no longer imply that the controller beats every fixed policy. Its role is to measure how much of the benefit of waiting a client can recover from its own response history, and the diagnostics show where that stops.

### 3. The long wait follows 26% of independent-error retries (R1; R2 item 3)

**New analysis: Section V-C and Fig. 1 (`threshold_tradeoff()` in `run_diagnostics.py`).** We swept k = 2–5 and β_long = 1–3 with β_short and W fixed. We also tested a circuit-breaker-style failure-rate rule, which takes the long wait only when at least half of the recent responses failed.

- **The false-alarm rate is set by k.** At 27% IID errors it was 59%, 26%, 8% and 2.5% for k = 2, 3, 4 and 5.
- **Detection falls in step.** Long waits after outage failures were 88%, 64%, 37% and 25%, and extended-outage delivery was 71.0%, 50.5%, 33.2% and 28.3%.
- **β_long changes the cost, not the rate.** It barely changed how often the long wait was chosen (24–29% at k = 3). It set what each false alarm cost and whether the long waits outlasted the outage.
- **The failure-rate rule did no better than k = 4.** It gave 17% false alarms and 35% detection.
- **What the false alarms cost.** Against the short wait alone, they cost 3.5 points at 27% errors and 5.2 points under tight deadlines, pooled over the workflows.
- **Conclusion.** Every setting trades one kind of delivery for the other, and none came within 5 points of perfect detection on both axes. Cutting false alarms needs a better detector, not a different threshold.

### 4. The localhost HTTP test cannot rank waiting policies (R2 item 4)

**Revised: Section V-G.**

- **What it establishes.** The decision code used in the simulation runs unchanged against a real socket server. It reads status codes and `Retry-After` headers, treats client timeouts as retryable, and keeps its waits in wall-clock time.
- **What it does not establish.**
  - It cannot rank the waiting policies: all four passed every shared-fault run, and each regime repeats one fixed schedule.
  - It says nothing about real providers, network latency or concurrent clients.
- **Layout change.** The table became two sentences to make room within the five-page limit.

### 5. W = 6 s was chosen just under the 6.5-s first outage (R2 item 5)

**Revised: Sections III-B and V-D.**

- Section III-B now states that W was set with knowledge of the simulator's outage windows, which a real client could not do.
- Section V-D describes practical calibration. A client would replay its own logged responses through the controller to measure the false-alarm rate at the observed background error rate. Incident records would give outage lengths that W should not exceed. W and k would then be chosen together to meet a false-alarm budget while still detecting the logged outages.

### 6. No comparison with production SDK or circuit-breaker libraries (R2 item 6)

**Revised: Section II, which explains why the proxy is a reasonable stand-in, and Section VI, which says what a real comparison would add.**

- **The proxy keeps the two mechanisms that can act within one workflow:** a growing wait and a retry limit.
- **The state it leaves out cannot act within one workflow.**
  - In the standard retry mode as revised by AWS in 2026, a non-throttling retry takes 14 tokens from a 500-token per-client bucket. One reporting workflow makes at most 30 retries (420 tokens), so the quota cannot run out.
  - That mode's 50-ms base delay would put it close to the Immediate policy after a 5xx.
  - A Resilience4j breaker with default settings needs 100 calls before it computes a failure rate, and no workflow here makes more than 72.
- **What a real comparison would add** is the state that libraries share across a client's calls: quotas, adaptive rate limiters, and breakers that see failures from all workflows and, when open, stop calls and relieve the failing service. Testing that needs many concurrent workflows and a load-dependent service.

## Other changes to the manuscript

- **Corresponding author.** The author is marked with an asterisk, with a corresponding-author line and email. This follows the acceptance email, although with a single author it is optional.
- **Page limit.** The paper stays within ICNGN's five pages. Several items were moved out or shrunk to make room, and stay in the repository:
  - the IEA workflow diagram (old Fig. 1, `figures/workflow_structure.pdf`);
  - the paired-interval figure (old Fig. 2, `figures/heldout_differences.pdf`);
  - the per-workflow switching table (old Table IV, `tables/switching.tex`; its numbers are still quoted in Section V-B);
  - the HTTP table (old Table V);
  - the outage-length figure, which is now one column wide.
- **Writing.** The abstract and conclusion were rewritten for the new results, and several passages were tightened.
- **References.** The AWS retry-behaviour reference was re-accessed on 7 Nov 2026 for the 2026 quota figures.

## Code changes

| File | Change |
|---|---|
| `retrybench/model.py`, `retrybench/simulator.py` | New `Scenario.outage_load_delay_s` (default 0). Each request received during an outage pushes that window's end out by this amount. With the default, results are identical; this was checked seed for seed against the outage-length sweep. |
| `run_load_coupling.py` (new) | Load-coupled outages and the label-masking control under load, written to `results/load_coupling/`. |
| `run_diagnostics.py` | Adds `threshold_tradeoff()`, `devgrid_on_heldout()` and `pooled_heldout_contrast()`. |
| `make_tables.py`, `make_figures.py` | Add `tables/load_coupling.tex` (Table IV) and `figures/tradeoff.pdf` (Fig. 1). Redraw the outage-length figure at one column wide. |
| `audit_results.py` | 10 new reconciliation checks, including δ = 0 matching the scheduled-outage records seed for seed. |
| `verify_paper_numbers.py` | A claim for every new number in the text. The test-count check now also reads the count quoted in `main.tex`. |
| `tests/test_load_coupling.py` (new), `tests/test_diagnostics.py` | 11 new tests, 98 in total. |
| `build_word.py`, `README.md` | Corresponding-author line in the Word copy; README updated for the new parts. |

## Reproducing the revision

```bash
python -m pytest -q                 # 98 tests
python run_diagnostics.py           # threshold sweep, development grid on held-out cells, pooled contrast
python run_load_coupling.py         # Table IV and label masking under load
python audit_results.py && python make_tables.py && python make_figures.py
python verify_paper_numbers.py      # ALL TEXT NUMBERS MATCH DATA AND CODE
pdflatex main.tex && pdflatex main.tex
```

A full rerun from an empty `results/` directory took about 90 seconds and reproduced every result file byte for byte, with one exception. The localhost HTTP files differ only in wall-clock timings; their outcomes and call counts are the same.
