import numpy as np

from localization.grid_cells import GridCellEncoder


def test_grid_cell_encoder_is_deterministic():
    encoder = GridCellEncoder()
    first = encoder.encode(0.25, 0.75)
    second = encoder.encode(0.25, 0.75)

    assert isinstance(first, np.ndarray)
    assert first.shape == second.shape
    assert np.allclose(first, second)
