"""Paper figures, drawn at final IEEE print width so text is true size.

Fig. 1  figures/workflow_structure.pdf   - IEA task graph, drawn from retrybench.stratcom.TEMPLATES
Fig. 2  figures/heldout_differences.pdf  - paired contrasts, extended outage and tight deadlines (results/main)
Fig. 3  figures/outage_duration.pdf      - outage-length sweep, two-column (results/diagnostics)
"""
from pathlib import Path
import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from retrybench.stratcom import TEMPLATES as WORKFLOWS

ROOT = Path(__file__).parent
FIG = ROOT / 'figures'
read = lambda p: list(csv.DictReader(open(p)))
COL_W = 3.45
INK, MUTED, GRID = '#0b0b0b', '#52514e', '#d9d8d4'
# Fixed categorical order (validated: scripts/validate_palette.js, light surface): slot 1..4.
STYLE = {
    'history_adaptive':    dict(color='#2a78d6', marker='o', ls='-',  label='History-adaptive', lw=1.6),
    'observable_cooldown': dict(color='#eb6834', marker='^', ls='-',  label='Linear cooldown', lw=1.2),
    'exponential':         dict(color='#1baf7a', marker='s', ls='-',  label='Exponential backoff', lw=1.2),
    'immediate':           dict(color='#eda100', marker='x', ls='--', label='Immediate', lw=1.2),
}
ABBR = {'information_environment_assessment': 'IEA', 'live_fact_check_support': 'LFC',
        'communications_situation_report': 'CSR'}
TEMPLATES = list(ABBR)
plt.rcParams.update({'font.family': 'serif', 'font.serif': ['Times New Roman', 'Liberation Serif', 'Times', 'DejaVu Serif'],
                     'font.size': 7.5, 'axes.labelsize': 7.5, 'xtick.labelsize': 7, 'ytick.labelsize': 7,
                     'legend.fontsize': 7, 'axes.edgecolor': MUTED, 'axes.labelcolor': INK,
                     'xtick.color': MUTED, 'ytick.color': MUTED, 'axes.linewidth': .6,
                     'pdf.fonttype': 42})


def save(fig, name):
    fig.savefig(FIG / f'{name}.pdf', bbox_inches='tight', pad_inches=.02)
    fig.savefig(FIG / f'{name}.png', dpi=200, bbox_inches='tight', pad_inches=.02)
    plt.close(fig)


# Fig. 1: the IEA task graph exactly as defined in the simulator (layers = longest path from a source).
LABELS = {'retrieve_public_feed': 'Retrieve\npublic feed', 'retrieve_official_bulletins': 'Retrieve\nbulletins',
          'normalise_and_deduplicate': 'Normalise,\ndeduplicate', 'extract_observed_topics': 'Extract\ntopics',
          'check_source_provenance': 'Check\nprovenance', 'cross_check_factual_claims': 'Cross-check\nsources',
          'optional_context_enrichment': 'Context\nenrichment', 'optional_visualisation': 'Visualise',
          'prepare_evidence_log': 'Evidence\nlog', 'queue_human_review': 'Queue for\nhuman review'}
ROW = {'retrieve_public_feed': 2, 'retrieve_official_bulletins': 1, 'normalise_and_deduplicate': 2,
       'cross_check_factual_claims': 0, 'extract_observed_topics': 2, 'check_source_provenance': 1,
       'optional_context_enrichment': 2, 'prepare_evidence_log': 1, 'optional_visualisation': 0, 'queue_human_review': 1}
steps = WORKFLOWS['information_environment_assessment']
layer = {}
for i, s in enumerate(steps):  # steps are listed in topological order
    layer[i] = 1 + max((layer[p] for p in s.predecessors), default=-1)
assert set(LABELS) == {s.name for s in steps} == set(ROW)
fig, ax = plt.subplots(figsize=(COL_W, 1.12))
BW, BH = .78, .66
boxes = {}
for i, s in enumerate(steps):
    x, y = layer[i], ROW[s.name]
    check = s.evidence_gate
    box = FancyBboxPatch((x - BW / 2, y - BH / 2), BW, BH, boxstyle='round,pad=0,rounding_size=.08',
                         fc='#dbe8f7' if check else '#f2f1ee', ec='#2a78d6' if check else MUTED,
                         lw=.7, ls=(0, (2.5, 1.5)) if s.criticality == 'optional' else '-', zorder=2)
    ax.add_patch(box)
    boxes[i] = box
    text = LABELS[s.name] + (f'\nTTL {s.freshness_ttl_s:g} s' if s.freshness_ttl_s else '')
    ax.text(x, y, text, ha='center', va='center', fontsize=5.6, color=INK, linespacing=1.0, zorder=3)
for i, s in enumerate(steps):
    for p in s.predecessors:
        ax.add_patch(FancyArrowPatch(posA=(layer[p], ROW[steps[p].name]), posB=(layer[i], ROW[s.name]),
                                     patchA=boxes[p], patchB=boxes[i], arrowstyle='-|>', mutation_scale=5,
                                     lw=.55, color=MUTED, shrinkA=0, shrinkB=.5, zorder=1))
ax.set_xlim(-.45, max(layer.values()) + .45)
ax.set_ylim(-.38, 2.38)
ax.axis('off')
fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
save(fig, 'workflow_structure')

# Fig. 3: success versus outage extension, small multiples by workflow (two-column figure).
rows = read(ROOT / 'results/diagnostics/outage_duration_summary.csv')
fig, axes = plt.subplots(1, 3, figsize=(7.0, 1.75), sharey=True)
for ax, template in zip(axes, TEMPLATES):
    for pol in ('immediate', 'exponential', 'observable_cooldown', 'history_adaptive'):
        st = STYLE[pol]
        pts = sorted((float(r['extension_s']), float(r['success_pct'])) for r in rows
                     if r['template'] == template and r['policy'] == pol)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=st['color'], ls=st['ls'], lw=st['lw'],
                marker=st['marker'], ms=3.6, mew=.9, label=st['label'], zorder=3 if pol == 'history_adaptive' else 2)
    ax.axvline(2, color=MUTED, lw=.6, ls=':', zorder=1)
    ax.set_title(ABBR[template], fontsize=7.5, color=INK, pad=2)
    ax.set_xticks([0, 2, 4, 6])
    ax.set_xlim(-.4, 6.4)
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.grid(axis='y', color=GRID, lw=.5)
    ax.tick_params(length=2, pad=1.5)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
axes[0].set_ylabel('Timely fresh delivery (%)')
axes[1].set_xlabel('Outage-window extension beyond development length (simulated s)')
axes[0].text(2.15, 97, 'primary\ntest', fontsize=6, color=MUTED, va='top')
handles, labels = axes[0].get_legend_handles_labels()
order = [3, 2, 1, 0]
fig.legend([handles[i] for i in order], [labels[i] for i in order], loc='upper center', ncol=4,
           frameon=False, bbox_to_anchor=(.53, 1.04), handlelength=2.2, columnspacing=1.6, handletextpad=.5)
fig.subplots_adjust(wspace=.08, left=.07, right=.995, bottom=.2, top=.84)
save(fig, 'outage_duration')

# Fig. 2: paired history-adaptive minus comparator, extended outage (top) and tight deadlines (bottom).
paired = {(r['template'], r['scenario'], r['compared_with']): r
          for r in read(ROOT / 'results/main/heldout_paired_bootstrap.csv') if r['split'] == 'held_out'}
PANELS = [('held_outage_extended', 'Extended outage', ('exponential', 'observable_cooldown')),
          ('held_tight_17', 'Tight IID 17%', ('exponential', 'immediate'))]
fig, axes = plt.subplots(2, 1, figsize=(COL_W, 2.55), sharex=True)
for ax, (scenario, title, comparators) in zip(axes, PANELS):
    keys = [(t, c) for t in TEMPLATES for c in comparators]
    for i, (template, comp) in enumerate(keys):
        r = paired[(template, scenario, comp)]
        y = len(keys) - 1 - i
        st = STYLE[comp]
        diff, lo, hi = float(r['difference_pp']), float(r['ci_low']), float(r['ci_high'])
        ax.plot([lo, hi], [y, y], color=st['color'], lw=2, solid_capstyle='round')
        ax.plot(diff, y, marker=st['marker'], color=st['color'], ms=4.5, mec='white' if st['marker'] != 'x' else INK, mew=.6 if st['marker'] != 'x' else .9)
        label = f'{diff:+.1f}'.replace('-', '\u2212')
        if hi < 0:  # label negative effects on the left so they do not cross the zero line
            ax.text(lo - 1.2, y, label, va='center', ha='right', fontsize=6.5, color=INK)
        else:
            ax.text(hi + 1.2, y, label, va='center', fontsize=6.5, color=INK)
    ax.axvline(0, color=MUTED, lw=.7, ls='--')
    ax.set_yticks(range(len(keys)))
    ax.set_yticklabels([f"{ABBR[t]} vs {STYLE[c]['label'].lower()}" for t, c in reversed(keys)], color=INK)
    ax.set_title(title, fontsize=7.5, color=INK, loc='left', pad=2)
    ax.grid(axis='x', color=GRID, lw=.5)
    ax.tick_params(length=2, pad=1.5)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
axes[1].set_xlim(-50, 50)
axes[1].set_xticks([-40, -20, 0, 20, 40])
axes[1].set_xlabel('History-adaptive minus comparator (percentage points), seed-paired 95% CI')
fig.subplots_adjust(left=.36, right=.99, bottom=.14, top=.95, hspace=.32)
save(fig, 'heldout_differences')

print('figures written')
