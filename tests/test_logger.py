from gemini_app.logger import get_logger, setup_logging


def test_setup_logging_level(capsys):
    """ログレベルのセットアップが正常に反映されるか検証."""
    setup_logging(level_name="DEBUG")
    logger = get_logger("test_module")

    logger.debug("デバッグメッセージテスト")
    logger.info("インフォメッセージテスト")

    captured = capsys.readouterr()
    assert "デバッグメッセージテスト" in captured.err
    assert "インフォメッセージテスト" in captured.err


def test_info_log_only(capsys):
    """INFO レベル設定時に DEBUG ログが出力されないか検証."""
    setup_logging(level_name="INFO")
    logger = get_logger("test_module")

    logger.debug("このログは出力されないはず")
    logger.info("このログは出力される")

    captured = capsys.readouterr()
    assert "このログは出力されないはず" not in captured.err
    assert "このログは出力される" in captured.err
