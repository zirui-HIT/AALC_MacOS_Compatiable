"""Regression checks must never write to the real installed app's settings."""

import atexit
import os
import shutil
import tempfile

if "AALC_DATA_ROOT" not in os.environ:
    _test_data_root = tempfile.mkdtemp(prefix="aalc-tests-")
    os.environ["AALC_DATA_ROOT"] = _test_data_root
    atexit.register(shutil.rmtree, _test_data_root, ignore_errors=True)
