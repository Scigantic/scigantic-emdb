"""Locations and the shared HTTP session."""
from __future__ import annotations
import os


MOUNT = os.environ.get("SCIGANTIC_MOUNT_PATH", "/mnt/http-archive/data")

CATALOG_URL = os.environ.get(
    "SCIGANTIC_EMDB_CATALOG",
    "https://scigantic-empiar-catalog.s3.amazonaws.com/emdb-catalog.json.gz",
)

FTP = "https://ftp.ebi.ac.uk/pub/databases/emdb/structures"

SUBDIRS = ("map", "header", "images", "masks", "other", "fsc", "metadata")

def _session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s = requests.Session()
    # EBI stalls ~3% of requests regardless of concurrency; retry beats waiting.
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=3, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504))))
    return s
