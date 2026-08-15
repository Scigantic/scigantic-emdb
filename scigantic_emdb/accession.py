"""Accession normalisation and the URLs derived from it."""
from __future__ import annotations
from .config import FTP, MOUNT


def acc(entry_id):
    """Normalize 339 / '339' / 'EMD-339' / 'emd_0339' → 'EMD-0339'.

    Zero-padding is not cosmetic. EMDB accessions are always at least four
    digits: EMD-0339 exists and EMD-339 does not, and across the whole archive
    there is no case where a padded and an unpadded form are different entries
    (961 padded accessions, 0 collisions). Without the pad, load_map(339) builds
    a URL that 404s, which is exactly the sort of thing a user or the assistant
    would write and then have to debug.
    """
    s = str(entry_id).strip().upper().replace("EMD_", "EMD-")
    if s.startswith("EMD-"):
        s = s[4:]
    elif s.startswith("EMD"):
        s = s[3:].lstrip("-")
    s = s.strip()
    return f"EMD-{s.zfill(4)}" if s.isdigit() else f"EMD-{s}"

def map_path(entry_id, local=False):
    """Path to an entry's primary map, on the mount or at EBI."""
    a = acc(entry_id)
    n = a.split("-")[1]
    return (f"{MOUNT}/{a}/map/emd_{n}.map.gz" if not local
            else f"{FTP}/{a}/map/emd_{n}.map.gz")


SUBDIRS = ("map", "header", "images", "masks", "other", "fsc", "metadata")

def image_url(entry):
    """Public URL of an entry's published rendering, or "" if it has none.

    Takes a catalog row (dict or Series) rather than an accession, because the
    filename is NOT derivable: 93% are emd_<n>.png but the rest are things like
    1409.gif, wtVAT_ADP2.png and emd_5107_1.png. Constructing the canonical name
    and hoping would leave broken images on ~7% of gallery cards, so the catalog
    records the real filename and this just assembles the URL.
    """
    try:
        name = entry.get("image")
    except AttributeError:
        return ""
    if not name or name != name:
        return ""
    acc_id = entry.get("id")
    if not acc_id or acc_id != acc_id:
        return ""
    return f"{FTP}/{acc_id}/images/{name}"
