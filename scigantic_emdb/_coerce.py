"""NaN-safe coercions for DataFrame cells.

A column absent from a partial index reads back as NaN, and NaN is truthy in
Python. That single fact caused two shipped bugs: `if row.get("has_mask")`
passed every row, and `r.get("emdb_ids") or []` handed a float to a for-loop
("'float' object is not iterable"). Every read of a possibly-missing cell goes
through one of these.
"""


def _nonempty(v):
    if v is None or v != v:
        return False
    if isinstance(v, (list, tuple, set)):
        return len(v) > 0
    return bool(str(v).strip())

def _truthy(v):
    """NaN-safe truth. A missing column in a DataFrame reads back as NaN, which
    is truthy in Python, so `if r.get("has_mask")` would pass every row."""
    if v is None or (isinstance(v, float) and v != v):
        return False
    return bool(v)

def _num_ok(v, lo, hi):
    """Range check that EXCLUDES a record with no value for the field.

    Keeping such records would silently pad every molecular-weight filter with
    entries that never deposited a weight, which reads as a bigger result set
    than the data supports.
    """
    if lo is None and hi is None:
        return True
    if v is None or (isinstance(v, float) and v != v):
        return False
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    if lo is not None and x < lo:
        return False
    if hi is not None and x > hi:
        return False
    return True

def _as_list(v):
    """NaN-safe list coercion for a DataFrame cell that should hold a list.

    `v or []` is wrong here: a missing cell reads back as NaN, NaN is truthy, and
    the caller then iterates a float. Returns [] for missing, wraps a bare
    scalar, and passes a real list through.
    """
    if v is None or (isinstance(v, float) and v != v):
        return []
    if isinstance(v, (list, tuple, set)):
        return [x for x in v if x is not None and x == x]
    return [v]
