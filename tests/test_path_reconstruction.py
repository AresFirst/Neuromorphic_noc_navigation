import pytest

from loihi_planner.path_reconstruction import reconstruct_path_from_parent


def test_reconstruct_path_from_parent_returns_full_path():
    parent_trace = {0: None, 1: 0, 2: 0, 3: 1, 4: 3}
    assert reconstruct_path_from_parent(parent_trace, 0, 4) == [0, 1, 3, 4]


def test_reconstruct_path_from_parent_raises_when_path_does_not_reach_start():
    parent_trace = {0: None, 1: 2, 2: 1}
    with pytest.raises(ValueError):
        reconstruct_path_from_parent(parent_trace, 0, 1)
