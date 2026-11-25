from pathlib import Path


def test_runtime_paths_are_redirected_to_isolated_test_directory():
    from src import config

    test_root = Path(config.os.environ["MYOWNTMS_TEST_DATA_DIR"])
    assert config.DATA_DIR == test_root
    assert config.DATABASE_PATH == test_root / "tms.db"
    assert config.ATTACHMENTS_DIR == test_root / "attachments"
    assert config.EXPORTS_DIR == test_root / "exports"
