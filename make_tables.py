"""Write the paper's data tables straight from the result CSVs (no hand transcription).

tables/heldout_all.tex     - held-out timely fresh delivery, all workflows and policies
tables/label_masking.tex   - label-masking control (results/label_masking)
tables/switching.tex       - switching ablation (results/diagnostics)
"""
from pathlib import Path
import csv
from run_diagnostics import HELD_OUT
from retrybench.scenarios import MAIN_SCENARIOS

ROOT = Path(__file__).parent
OUT = ROOT / 'tables'
OUT.mkdir(exist_ok=True)
read = lambda p: list(csv.DictReader(open(p)))
TEMPLATES = [('information_environment_assessment', 'IEA'), ('live_fact_check_support', 'LFC'),
             ('communications_situation_report', 'CSR')]
POLICIES = [('immediate', 'Imm.'), ('exponential', 'Exp.'), ('sdk_style_proxy', 'SDK'),
            ('observable_cooldown', 'Cool.'), ('history_adaptive', 'Hist.')]
CONDITIONS = [('held_iid_27', 'IID 27\\%'), ('held_outage_extended', 'Extended outage'),
              ('held_tight_17', 'Tight IID 17\\%'), ('held_quota_23', 'Hinted quota'),
              ('held_mixed', 'Mixed permanent')]


def fmt(v: float) -> str:
    return f'{v:.1f}'


def pct(p: float) -> str:
    return f'{100 * p:g}\\%'


# Deadlines and background error rates of the held-out conditions, read from the scenario definitions.
_held = {s.name: s for s in HELD_OUT}
_iid, _out, _tight, _quota, _mixed = (_held[k] for k, _ in CONDITIONS)
CONDITION_NOTE = (f'Deadlines and background errors: IID, {_iid.deadline_s:g}~s; extended outage, {_out.deadline_s:g}~s, '
                  f'{pct(_out.failure_prob)} IID; tight, {_tight.deadline_s:g}~s; hinted quota ({_quota.provider_rps:g} requests/s), '
                  f'{_quota.deadline_s:g}~s, {pct(_quota.failure_prob)} IID; mixed, {_mixed.deadline_s:g}~s, '
                  f'{pct(_mixed.failure_prob)} IID and {pct(_mixed.permanent_prob)} permanent.')
_mask = {s.name: s for s in MAIN_SCENARIOS}['outage_45']


rows = {(r['template'], r['scenario'], r['policy']): float(r['success_pct'])
        for r in read(ROOT / 'results/main/heldout_summary.csv') if r['split'] == 'held_out'}
lines = [r'\begin{table*}[t]', r'\centering',
         r'\caption{Held-out timely fresh delivery (\%, $N=200$ matched seeds per cell). ' + CONDITION_NOTE +
         r' Imm.: immediate; Exp.: exponential backoff; '
         r'SDK: SDK-style proxy; Cool.: linear cooldown; Hist.: history-adaptive. Bold: best in the row within each workflow, ties included.}',
         r'\label{tab:main}', r'\footnotesize', r'\setlength{\tabcolsep}{3.4pt}',
         r'\begin{tabular}{@{}l*{5}{r}c*{5}{r}c*{5}{r}@{}}\toprule',
         ' & ' + ' && '.join(rf'\multicolumn{{5}}{{c}}{{{abbr}}}' for _, abbr in TEMPLATES) + r'\\',
         r'\cmidrule(lr){2-6}\cmidrule(lr){8-12}\cmidrule(lr){14-18}',
         'Condition & ' + ' && '.join(' & '.join(p for _, p in POLICIES) for _ in TEMPLATES) + r'\\\midrule']
for cond, label in CONDITIONS:
    groups = []
    for template, _ in TEMPLATES:
        vals = [rows[(template, cond, p)] for p, _ in POLICIES]
        best = max(vals)
        groups.append(' & '.join(rf'\textbf{{{fmt(v)}}}' if v == best else fmt(v) for v in vals))
    lines.append(f'{label} & ' + ' && '.join(groups) + r'\\')
lines[-1] += r'\bottomrule'
lines += [r'\end{tabular}', r'\end{table*}']
(OUT / 'heldout_all.tex').write_text('\n'.join(lines) + '\n')

# Single-column stacked variant for the editable Word copy (an 18-column table cannot fit a Word column).
stack = [r'\begin{table}[t]', r'\centering',
         r'\caption{Held-out timely fresh delivery (\%, $N=200$ matched seeds per cell). ' + CONDITION_NOTE + r' Bold: best in the row.}',
         r'\label{tab:main}', r'\begin{tabular}{@{}llrrrrr@{}}\toprule',
         'Workflow & Condition & ' + ' & '.join(p for _, p in POLICIES) + r'\\\midrule']
for template, abbr in TEMPLATES:
    for cond, label in CONDITIONS:
        vals = [rows[(template, cond, p)] for p, _ in POLICIES]
        best = max(vals)
        stack.append(f'{abbr} & {label} & ' + ' & '.join(rf'\textbf{{{fmt(v)}}}' if v == best else fmt(v) for v in vals) + r'\\')
stack[-1] += r'\bottomrule'
stack += [r'\end{tabular}', r'\end{table}']
(OUT / 'heldout_all_word.tex').write_text('\n'.join(stack) + '\n')

obs = {(r['template'], r['scenario'], r['policy']): float(r['fresh_pct'])
       for r in read(ROOT / 'results/label_masking/label_masking_summary.csv')}
MASK_POL = [('immediate', 'Immediate'), ('exponential', 'Exponential backoff'),
            ('budget_aware', 'Cause-aware'), ('observable_cooldown', 'Linear cooldown')]
lines = [r'\begin{table}[t]', r'\centering',
         r'\caption{Label-masking control: timely fresh delivery (\%, 200 seeds) when the outage cause is visible to the policy '
         r'(Vis.) or reported as a generic 5xx (Mask.). ' + f'{_mask.deadline_s:g}-s deadline, {pct(_mask.failure_prob)} background errors, '
         r'unextended outages.}',
         r'\label{tab:mask}', r'\scriptsize', r'\setlength{\tabcolsep}{3.5pt}',
         r'\begin{tabular}{@{}lrrcrrcrr@{}}\toprule',
         ' & ' + ' && '.join(rf'\multicolumn{{2}}{{c}}{{{abbr}}}' for _, abbr in TEMPLATES) + r'\\',
         r'\cmidrule(lr){2-3}\cmidrule(lr){5-6}\cmidrule(lr){8-9}',
         'Policy & ' + ' && '.join('Vis. & Mask.' for _ in TEMPLATES) + r'\\\midrule']
for pol, label in MASK_POL:
    lines.append(f'{label} & ' + ' && '.join(
        f"{fmt(obs[(t, 'outage_labeled', pol)])} & {fmt(obs[(t, 'outage_hidden_5xx', pol)])}" for t, _ in TEMPLATES) + r'\\')
lines[-1] += r'\bottomrule'
lines += [r'\end{tabular}', r'\end{table}']
(OUT / 'label_masking.tex').write_text('\n'.join(lines) + '\n')
sw = {(r['scenario'], r['template'], r['variant']): float(r['success_pct'])
      for r in read(ROOT / 'results/diagnostics/switching_ablation_summary.csv')}
VARIANTS = [('adaptive', 'Hist.'), ('short_only', 'Short'), ('long_only', 'Long'), ('perfect_detection', 'Perfect'),
            ('observable_cooldown', 'Cool.'), ('immediate', 'Imm.')]
lines = [r'\begin{table}[t]', r'\centering',
         r"\caption{Switching ablation: timely fresh delivery (\%, 200 held-out seeds). Short and Long fix the controller's wait at "
         r'$0.4a$ or $2.0a$~s; Perfect picks between them using the hidden outage label, as an upper bound. Cool.\ and Imm.\ as in Table~\ref{tab:main}. '
         r'Bold: best in the row.}',
         r'\label{tab:switch}', r'\scriptsize', r'\setlength{\tabcolsep}{3.2pt}',
         r'\begin{tabular}{@{}ll' + 'r' * len(VARIANTS) + r'@{}}\toprule',
         'Condition & & ' + ' & '.join(v for _, v in VARIANTS) + r'\\\midrule']
for cond, label in [('held_outage_extended', 'Extended outage'), ('held_tight_17', 'Tight IID 17\\%')]:
    for i, (template, abbr) in enumerate(TEMPLATES):
        vals = [sw[(cond, template, v)] for v, _ in VARIANTS]
        best = max(vals)
        cells = ' & '.join(rf'\textbf{{{fmt(x)}}}' if x == best else fmt(x) for x in vals)
        lines.append(f"{label if i == 0 else ''} & {abbr} & {cells}" + r'\\')
    if cond == 'held_outage_extended':
        lines.append(r'\addlinespace')
lines[-1] += r'\bottomrule'
lines += [r'\end{tabular}', r'\end{table}']
(OUT / 'switching.tex').write_text('\n'.join(lines) + '\n')
print('tables written')
