import pytest
from retrybench.model import Scenario, generate_workload


@pytest.mark.parametrize('shape', ['chain','fanout','layered'])
@pytest.mark.parametrize('n', [5,12,20])
def test_dags_are_valid_and_terminal(shape, n):
    w = generate_workload(42,n,shape)
    assert len(w.tasks) == n
    for t in w.tasks:
        assert all(0 <= p < t.task_id for p in t.predecessors)
    assert not w.tasks[0].predecessors
    seen = {0}
    for task in w.tasks[1:]:
        assert task.predecessors
        assert all(p in seen for p in task.predecessors)
        seen.add(task.task_id)
    # Every DAG task contributes to the final sink.
    upstream = {n-1}
    for i in range(n-1,-1,-1):
        if i in upstream:
            upstream.update(w.tasks[i].predecessors)
    assert len(upstream) == n


def test_trace_deterministic_and_no_global_rng_dependence():
    assert generate_workload(72) == generate_workload(72)
    assert generate_workload(73) != generate_workload(72)


def test_invalid_config():
    with pytest.raises(ValueError):
        generate_workload(42, shape='tree')
    with pytest.raises(ValueError):
        Scenario('bad',failure_prob=1.2)
