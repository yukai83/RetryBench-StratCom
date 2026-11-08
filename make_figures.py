"""Paper figures, drawn at final IEEE print width so text is true size.

Fig. 1  figures/tradeoff.pdf             - threshold trade-off: false alarms vs outage detection (results/diagnostics)
Fig. 2  figures/outage_duration.pdf      - outage-length sweep, single column (results/diagnostics)
Supplementary (left the paper in the camera-ready revision, for space):
        figures/workflow_structure.pdf   - IEA task graph, drawn from retrybench.stratcom.TEMPLATES
        figures/heldout_differences.pdf  - paired contrasts, extended outage and tight deadlines (results/main)
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


# Supplementary figure: the IEA task graph exactly as defined in the simulator (layers = longest path from a source).
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

# Fig. 2: success versus outage extension, small multiples by workflow (single column since the revision).
rows = read(ROOT / 'results/diagnostics/outage_duration_summary.csv')
fig, axes = plt.subplots(1, 3, figsize=(COL_W, 1.55), sharey=True)
for ax, template in zip(axes, TEMPLATES):
    for pol in ('immediate', 'exponential', 'observable_cooldown', 'history_adaptive'):
        st = STYLE[pol]
        pts = sorted((float(r['extension_s']), float(r['success_pct'])) for r in rows
                     if r['template'] == template and r['policy'] == pol)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=st['color'], ls=st['ls'], lw=st['lw'] * .85,
                marker=st['marker'], ms=2.8, mew=.8, label=st['label'], zorder=3 if pol == 'history_adaptive' else 2)
    ax.axvline(2, color=MUTED, lw=.6, ls=':', zorder=1)
    ax.set_title(ABBR[template], fontsize=7, color=INK, pad=1.5)
    ax.set_xticks([0, 2, 4, 6])
    ax.set_xlim(-.4, 6.4)
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.grid(axis='y', color=GRID, lw=.5)
    ax.tick_params(length=2, pad=1.2, labelsize=6.3)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
axes[0].set_ylabel('Timely fresh delivery (%)', fontsize=6.8)
axes[1].set_xlabel('Outage extension beyond development length (s)', fontsize=6.8)
axes[0].text(2.25, 97, 'primary\ntest', fontsize=5.5, color=MUTED, va='top', linespacing=.9)
handles, labels = axes[0].get_legend_handles_labels()
order = [3, 2, 1, 0]
fig.legend([handles[i] for i in order], ['History-adaptive', 'Cooldown', 'Exponential', 'Immediate'], loc='upper center', ncol=4,
           frameon=False, bbox_to_anchor=(.55, 1.03), handlelength=1.8, columnspacing=.9, handletextpad=.35, fontsize=6.3)
fig.subplots_adjust(wspace=.1, left=.13, right=.99, bottom=.22, top=.8)
save(fig, 'outage_duration')

# Supplementary figure: paired history-adaptive minus comparator, extended outage (top) and tight deadlines (bottom).
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

# Fig. 1 (revision): the threshold trade-off. Every point pools the three workflows (600 runs per condition).
trade = read(ROOT / 'results/diagnostics/threshold_tradeoff.csv')
held = {(r['template'], r['scenario'], r['policy']): float(r['success_pct'])
        for r in read(ROOT / 'results/main/heldout_summary.csv') if r['split'] == 'held_out'}
switch = {(r['scenario'], r['template'], r['variant']): float(r['success_pct'])
          for r in read(ROOT / 'results/diagnostics/switching_ablation_summary.csv')}
INDEP, OUT_SC = ('held_iid_27', 'held_tight_17'), 'held_outage_extended'


def tradeoff_point(k, long, rho=''):
    rows = {r['scenario']: r for r in trade if (int(r['threshold']), float(r['long_s']), r['failure_rate_rule']) == (k, long, rho)}
    x = sum(float(rows[s]['success_pct_pooled']) for s in INDEP) / 2
    return x, float(rows[OUT_SC]['success_pct_pooled']), float(rows['held_iid_27']['long_wait_pct_independent'])


def reference_point(get):
    return (sum(get(s, t) for s in INDEP for t in TEMPLATES) / (2 * len(TEMPLATES)),
            sum(get(OUT_SC, t) for t in TEMPLATES) / len(TEMPLATES))


fig, ax = plt.subplots(figsize=(COL_W, 1.7))
blue = STYLE['history_adaptive']['color']
for long, ls, ms, alpha in ((1.5, (0, (3, 1.5)), 3.2, .55), (2., '-', 4.2, 1.)):
    pts = [tradeoff_point(k, long) for k in (2, 3, 4, 5)]
    ax.plot([p[0] for p in pts], [p[1] for p in pts], color=blue, ls=ls, lw=1.3, marker='o', ms=ms, alpha=alpha,
            mec='white', mew=.6, zorder=3)
    if long == 2.:
        for k, (x, y, fa) in zip((2, 3, 4, 5), pts):
            dx, dy, ha = {2: (-.4, -6.5, 'right'), 3: (1.2, 1.0, 'left'), 4: (1.0, 1.2, 'left'), 5: (1.0, -.4, 'left')}[k]
            ax.text(x + dx, y + dy, f'$k$={k} ({fa:.0f}%)', fontsize=6.2, color=INK, ha=ha, va='center')
        fx, fy, _ = pts[1]
        ax.plot(fx, fy, marker='o', ms=8.5, mfc='none', mec=INK, mew=.8, zorder=4)
    else:
        x, y, _ = pts[0]
        ax.text(x, y + 3.8, r'$k$=2, $\beta_{\rm long}$=1.5', fontsize=6.2, color=MUTED, ha='center', va='center')
for rho in ('0.5', '0.6'):
    x, y, _ = tradeoff_point(3, 2., rho)
    ax.plot(x, y, marker='D', ms=3.6, mfc='white', mec=blue, mew=.9, zorder=3)
x5, y5, _ = tradeoff_point(3, 2., '0.5')
ax.text(x5 - .9, y5 - 3.0, 'failure-rate\nrule', fontsize=6.2, color=MUTED, ha='right', va='center', linespacing=.95)
refs = [('observable_cooldown', 'Linear cooldown', (-1.0, 0., 'right')), ('exponential', 'Exponential', (-1.0, 0., 'right')),
        ('immediate', 'Immediate', (0., -5.5, 'center'))]
for pol, label, (dx, dy, ha) in refs:
    st = STYLE[pol]
    x, y = reference_point(lambda s, t, p=pol: held[(t, s, p)])
    ax.plot(x, y, marker=st['marker'], color=st['color'], ms=5.5, mew=1.1, ls='none', zorder=3,
            mec='white' if st['marker'] != 'x' else st['color'])
    ax.text(x + dx, y + dy, label, fontsize=6.2, color=INK, ha=ha, va='center')
x, y = reference_point(lambda s, t: switch[(s, t, 'perfect_detection')])
ax.plot(x, y, marker='*', ms=7.5, mfc='white', mec=INK, mew=.8, ls='none', zorder=3)
ax.text(x, y - 6.0, 'Perfect detection (bound)', fontsize=6.2, color=INK, ha='center', va='center')
ax.set_xlim(66, 98)
ax.set_ylim(10, 84)
ax.set_xticks([70, 75, 80, 85, 90, 95])
ax.set_yticks([20, 40, 60, 80])
ax.set_xlabel('Independent faults: mean of IID 27% and tight 17% (%)')
ax.set_ylabel('Extended outage (%)')
ax.grid(color=GRID, lw=.5)
ax.tick_params(length=2, pad=1.5)
for side in ('top', 'right'):
    ax.spines[side].set_visible(False)
fig.subplots_adjust(left=.13, right=.99, bottom=.2, top=.98)
save(fig, 'tradeoff')

print('figures written')
