"""Reference scenario catalogue.

Used by the label-masking control (Table I of the paper) and by policy regression tests.
"""
from .model import Scenario

MAIN_SCENARIOS = (
    Scenario('control_no_failure', failure_prob=0., timeout_s=100, deadline_s=90),
    Scenario('iid_low_05', failure_prob=.05, deadline_s=45),
    Scenario('iid_medium_20', failure_prob=.20, deadline_s=45),
    Scenario('iid_high_35', failure_prob=.35, deadline_s=45),
    Scenario('iid_tight_15', failure_prob=.20, deadline_s=15),
    Scenario('outage_45', failure_prob=.08, use_outages=True, deadline_s=45),
    Scenario('rate_limit_hinted', failure_prob=.08, provider_rps=1.8,
             burst_tokens=2., deadline_s=60, advertise_retry_after=True),
    Scenario('rate_limit_unhinted', failure_prob=.08, provider_rps=1.8,
             burst_tokens=2., deadline_s=60, advertise_retry_after=False),
    Scenario('permanent_05', failure_prob=.08, permanent_prob=.05, deadline_s=45),
)
