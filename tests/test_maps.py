"""maps.py — slices() smoke test. Pure numpy/matplotlib, no network, no mrcfile.

load_map() needs either the FUSE mount or a live EBI fetch, so it is not
covered here. slices() only needs an in-memory volume, so it gets a basic
smoke test: three orthogonal sections through a small synthetic array.
"""
import matplotlib

matplotlib.use("Agg")

import numpy as np

from scigantic_emdb.maps import slices


def test_slices_returns_three_panels_for_a_small_volume():
    vol = np.random.default_rng(0).random((8, 10, 12)).astype("float32")
    fig = slices(vol)
    try:
        assert len(fig.axes) == 3
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_slices_handles_a_flat_volume_without_error():
    """A constant volume makes percentile lo == hi; the imshow call must not
    divide by a zero range."""
    vol = np.zeros((6, 6, 6), dtype="float32")
    fig = slices(vol)
    try:
        assert len(fig.axes) == 3
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)
