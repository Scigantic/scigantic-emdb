"""Reading a map and looking at it."""
from __future__ import annotations
import gzip
import os
import shutil

from .accession import acc, map_path
from .config import _session


def load_map(entry_id, cache_dir="/tmp/emdb", permissive=True):
    """Decompress and open an EMDB map. Returns (numpy array, metadata dict).

    Maps ship gzipped, and ``mrcfile`` needs random access, so streaming a gzip
    straight off the FUSE mount is slow. This decompresses to local disk once
    and reuses it — the six lines everyone writes, written once.
    """
    import mrcfile
    import numpy as np
    a = acc(entry_id)
    os.makedirs(cache_dir, exist_ok=True)
    local = os.path.join(cache_dir, f"{a}.map")
    if not os.path.exists(local) or os.path.getsize(local) == 0:
        src = map_path(a)
        if os.path.exists(src):
            with gzip.open(src, "rb") as fh, open(local, "wb") as out:
                shutil.copyfileobj(fh, out, length=8 << 20)
        else:  # not mounted (e.g. running outside a notebook) — fetch from EBI
            import io
            r = _session().get(map_path(a, local=True), timeout=120)
            r.raise_for_status()
            with gzip.open(io.BytesIO(r.content), "rb") as fh, open(local, "wb") as out:
                shutil.copyfileobj(fh, out, length=8 << 20)
    with mrcfile.open(local, permissive=permissive) as m:
        vol = np.array(m.data)
        vs = m.voxel_size
        meta = {
            "shape": tuple(int(s) for s in vol.shape),
            "dtype": str(vol.dtype),
            "voxel_size_a": tuple(round(float(v), 3) for v in (vs.x, vs.y, vs.z)),
            "path": local,
            "size_mb": round(os.path.getsize(local) / 1e6, 1),
        }
    return vol, meta

def slices(vol, cmap="gray", figsize=(12, 4), percentile=(1, 99)):
    """Central sections through all three axes — the fastest look at a map.

    Contrast is stretched per-panel on a percentile range. Cryo-EM maps carry
    outliers that flatten a naive min/max scale to featureless grey; that was a
    real defect in the EMPIAR thumbnails, so it is handled here from the start.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    z, y, x = [s // 2 for s in vol.shape]
    panels = [(vol[z], "XY"), (vol[:, y], "XZ"), (vol[:, :, x], "YZ")]
    fig, ax = plt.subplots(1, 3, figsize=figsize)
    for a_, (img, t) in zip(ax, panels):
        lo, hi = np.percentile(img, percentile)
        a_.imshow(img, cmap=cmap, vmin=lo, vmax=hi if hi > lo else None)
        # Equal aspect: anisotropic voxels otherwise render a squashed map, the
        # distortion that made the first EMPIAR thumbnail set unusable.
        a_.set_aspect("equal")
        a_.set_title(t, fontsize=9)
        a_.axis("off")
    fig.tight_layout()
    return fig
