"""files.py — the HTTPS fallback must fail loudly, not silently.

_entry_files_http() previously caught every exception around its requests
calls and returned {}. entry_files()'s own docstring says the HTTPS fallback
exists specifically so a caller can tell "I could not look" apart from "this
entry deposited nothing" — catching and returning {} collapsed exactly that
distinction back down. These pin the fix: a request failure must propagate,
not come back as an empty (and misleading) result.
"""
import requests

import pytest

from scigantic_emdb import files


class _RaisingSession:
    """Session stand-in whose .get() always fails before a response exists."""

    def get(self, *args, **kwargs):
        raise requests.exceptions.ConnectionError("simulated network failure")


class _HttpErrorSession:
    """Session stand-in whose response 404s on raise_for_status()."""

    class _Resp:
        def raise_for_status(self):
            raise requests.exceptions.HTTPError("404 Client Error")

    def get(self, *args, **kwargs):
        return self._Resp()


def test_entry_files_http_propagates_connection_failures(monkeypatch):
    monkeypatch.setattr(files, "_session", lambda: _RaisingSession())
    with pytest.raises(requests.exceptions.ConnectionError):
        files._entry_files_http("EMD-9999")


def test_entry_files_http_propagates_http_status_errors(monkeypatch):
    monkeypatch.setattr(files, "_session", lambda: _HttpErrorSession())
    with pytest.raises(requests.exceptions.HTTPError):
        files._entry_files_http("EMD-9999")


def test_entry_files_http_never_silently_returns_empty_on_failure(monkeypatch):
    """Regression guard for the exact bug: previously this returned {} — the
    same shape as a real, successful "nothing deposited" result — for both a
    connection failure and an HTTP error. Assert it raises instead."""
    for session in (_RaisingSession(), _HttpErrorSession()):
        monkeypatch.setattr(files, "_session", lambda s=session: s)
        try:
            files._entry_files_http("EMD-9999")
        except Exception:
            continue
        raise AssertionError(
            "_entry_files_http() returned instead of raising on a request failure"
        )
