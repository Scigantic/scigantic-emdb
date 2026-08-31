"""accession.py — id normalisation and zero-padding (pure, no network).

EMDB accessions are always at least four digits (EMD-0339, never EMD-339);
acc() is the single place that gets this right so callers don't build a URL
that 404s on an unpadded id.
"""
from scigantic_emdb.accession import acc, image_url, map_path
from scigantic_emdb.config import FTP, MOUNT


def test_acc_normalizes_bare_int():
    assert acc(339) == "EMD-0339"


def test_acc_normalizes_bare_str():
    assert acc("339") == "EMD-0339"


def test_acc_normalizes_dashed_unpadded_form():
    assert acc("EMD-339") == "EMD-0339"


def test_acc_normalizes_underscored_padded_form():
    assert acc("emd_0339") == "EMD-0339"


def test_acc_is_idempotent_on_already_padded_form():
    assert acc("EMD-0339") == "EMD-0339"


def test_acc_handles_no_separator_form():
    assert acc("EMD339") == "EMD-0339"


def test_acc_lowercase_input():
    assert acc("emd-339") == "EMD-0339"


def test_acc_does_not_truncate_ids_already_past_four_digits():
    assert acc(12345) == "EMD-12345"


def test_map_path_mount_form_uses_padded_accession():
    p = map_path(339)
    assert p == f"{MOUNT}/EMD-0339/map/emd_0339.map.gz"


def test_map_path_remote_form_uses_padded_accession():
    p = map_path(339, local=True)
    assert p == f"{FTP}/EMD-0339/map/emd_0339.map.gz"


def test_image_url_missing_row_returns_empty():
    assert image_url({}) == ""


def test_image_url_missing_image_name_returns_empty():
    assert image_url({"image": None, "id": "EMD-0339"}) == ""


def test_image_url_missing_id_returns_empty():
    assert image_url({"image": "emd_0339.png", "id": None}) == ""


def test_image_url_builds_from_row():
    row = {"id": "EMD-0339", "image": "emd_0339.png"}
    assert image_url(row) == f"{FTP}/EMD-0339/images/emd_0339.png"


def test_image_url_preserves_nonstandard_filename():
    """~7% of entries don't follow the emd_<n>.png convention (e.g. a .gif or
    a suffixed name); the real deposited filename must pass through as-is."""
    row = {"id": "EMD-1409", "image": "1409.gif"}
    assert image_url(row) == f"{FTP}/EMD-1409/images/1409.gif"
