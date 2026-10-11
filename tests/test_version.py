"""The version a package reports must be the version it was released as.

`scigantic_emdb.__version__` said 0.4.2 in the 0.4.3 release because the constant and
`pyproject.toml` are bumped by hand in two places. Fixed in 0.5.0; this keeps it fixed.
"""
import os
import re

import scigantic_emdb


def test_version_constant_matches_pyproject():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "pyproject.toml")
    with open(path, encoding="utf-8") as fh:
        declared = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M).group(1)
    assert scigantic_emdb.__version__ == declared
