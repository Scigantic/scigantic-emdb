"""config.py — the shared HTTP session (no network)."""
import threading

from scigantic_emdb.config import _session


def test_session_is_reused_across_calls():
    """_session() used to build a brand-new requests.Session (and connection
    pool) on every call. It must now return the same instance, so repeated
    calls from catalog.load()/files.entry_files()/maps.load_map() reuse one
    connection pool instead of paying a fresh handshake each time."""
    assert _session() is _session()


def test_session_lazy_init_is_race_free():
    """Many threads calling _session() for the first time at once must all
    land on the same instance, not each build (and leak) their own."""
    import scigantic_emdb.config as config
    config._session_instance = None  # force a fresh race

    results = [None] * 32

    def _get(i):
        results[i] = _session()

    threads = [threading.Thread(target=_get, args=(i,)) for i in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({id(r) for r in results}) == 1
