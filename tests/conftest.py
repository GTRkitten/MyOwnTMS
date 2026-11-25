"""Keep every test import and database operation away from runtime data."""

import os
import shutil
import tempfile
from pathlib import Path


_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="myowntms-tests-"))
os.environ["MYOWNTMS_TESTING"] = "1"
os.environ["MYOWNTMS_TEST_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)
