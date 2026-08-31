"""What an entry actually deposited, from the mount or over HTTPS."""
from __future__ import annotations
import os

from .accession import acc
from .config import FTP, MOUNT, SUBDIRS, _session


def entry_files(entry_id):
    """What this entry actually deposited, per subdirectory.

    Half-maps, masks and FSC curves are per-deposition, not universal. Returns
    only the subdirectories that exist, so callers can check instead of
    assuming — nothing should tell a user a half-map is there without looking.

    Falls back to listing over HTTPS when the archive is not mounted, matching
    load_map. Without that the two disagreed: load_map worked off-mount and
    entry_files silently returned {}, which reads as "this entry deposited
    nothing" rather than "I could not look".
    """
    a = acc(entry_id)
    root = f"{MOUNT}/{a}"
    if os.path.isdir(root):
        out = {}
        for sub in SUBDIRS:
            p = os.path.join(root, sub)
            if os.path.isdir(p):
                try:
                    out[sub] = sorted(os.listdir(p))
                except OSError:
                    pass
        return out
    return _entry_files_http(a)

def _entry_files_http(a):
    """List an entry's subdirectories from EBI's autoindex over HTTPS.

    Deliberately does not catch request failures. Swallowing them into {}
    would reproduce the exact ambiguity entry_files() exists to avoid: a
    caller cannot tell "EBI could not be reached" from "this entry deposited
    nothing". Let requests.exceptions.RequestException (timeout, connection
    error, non-2xx status) propagate instead, matching EmdbCatalog.load().
    """
    import re
    s = _session()
    top = s.get(f"{FTP}/{a}/", timeout=30)
    top.raise_for_status()
    present = set(re.findall(r'href="([a-z_]+)/"', top.text)) & set(SUBDIRS)
    out = {}
    for sub in SUBDIRS:
        if sub not in present:
            continue
        r = s.get(f"{FTP}/{a}/{sub}/", timeout=30)
        r.raise_for_status()
        names = re.findall(r'href="([^"/?][^"/]*)"', r.text)
        out[sub] = sorted(n for n in names if "." in n)
    return out
