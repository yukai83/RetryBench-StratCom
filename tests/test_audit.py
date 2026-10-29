import csv
import pytest
from retrybench.audit import audit_directory
from retrybench.experiment import run_study


def test_audit_and_exact_replay(tmp_path):
    run_study(tmp_path, replicates=6, scenarios=['perfect_control','iid_medium'], n_tasks=6,
              shape='layered', make_plots=False)
    report=audit_directory(tmp_path)
    assert report['valid'] and report['records']==48


def test_audit_detects_modified_results(tmp_path):
    run_study(tmp_path, replicates=3, scenarios=['perfect_control'], n_tasks=6,
              make_plots=False)
    path=tmp_path/'replicate_metrics.csv'
    text=path.read_text()
    # Corrupt one data row's success status without changing the row count.
    text=text.replace(',True,', ',False,', 1)
    path.write_text(text)
    with pytest.raises(ValueError):
        audit_directory(tmp_path)
