"""Locations and the shared HTTP session."""
from __future__ import annotations
import os
import threading


MOUNT = os.environ.get("SCIGANTIC_MOUNT_PATH", "/mnt/http-archive/data")

CATALOG_URL = os.environ.get(
    "SCIGANTIC_EMDB_CATALOG",
    "https://scigantic-empiar-catalog.s3.amazonaws.com/emdb-catalog.json.gz",
)

FTP = "https://ftp.ebi.ac.uk/pub/databases/emdb/structures"

SUBDIRS = ("map", "header", "images", "masks", "other", "fsc", "metadata")

_session_instance = None
_session_lock = threading.Lock()


def _session():
    """The shared, retry-enabled session, built once and reused.

    Every caller (catalog.load(), files.entry_files(), maps.load_map()) used
    to get a brand-new Session, and with it a brand-new connection pool, on
    every single call: no keep-alive reuse between calls, so a loop of
    load_map() over many entries paid a fresh TCP+TLS handshake to
    ftp.ebi.ac.uk each time. Lazily building one session and reusing it is
    the same fix scigantic-wwpdb's _http.py and scigantic-pubchem's
    _get_session() already apply, for the same reason.

    Guarded by a lock so two threads racing the first call (e.g. with_empiar()
    fanning out over many entries) can't both see None and each construct
    their own session, leaking a connection pool. requests.Session is
    documented thread-safe for issuing requests once constructed; only the
    lazy-init race needs guarding.
    """
    global _session_instance
    if _session_instance is None:
        with _session_lock:
            if _session_instance is None:  # another thread may have won the race
                import requests
                from requests.adapters import HTTPAdapter
                from urllib3.util.retry import Retry
                s = requests.Session()
                # EBI stalls ~3% of requests regardless of concurrency; retry beats waiting.
                s.mount("https://", HTTPAdapter(max_retries=Retry(
                    total=3, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504))))
                _session_instance = s
    return _session_instance
