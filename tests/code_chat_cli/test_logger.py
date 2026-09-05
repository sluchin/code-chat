"""`code_chat_cli.logger` モジュールにおけるログフォーマット, 出力レベル設定, およびファイル出力のテスト."""

import logging
import os
import socket
from unittest.mock import patch

from code_chat_cli.logger import (
    get_logger,
    setup_logging,
    syslog_context_filter,
)


def test_setup_logging_app_logger_level():
    """setup_logging が app_logger と handler のレベルを正しく更新するか検証."""
    setup_logging("DEBUG")

    app_logger = logging.getLogger("code_chat_cli")
    root_logger = logging.getLogger()

    assert app_logger.level == logging.DEBUG
    assert len(root_logger.handlers) > 0
    assert root_logger.handlers[0].level == logging.DEBUG


def test_syslog_context_filter():
    """正常系: LogRecord に syslog 属性（syslog_time, hostname, pid, app_name）が付与されるか検証."""
    # テスト用のダミー LogRecord を作成
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test_path.py",
        lineno=10,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    # 動的属性をあらかじめ定義しておくことで Pylint の E1101 を回避
    record.syslog_time = ""
    record.hostname = ""
    record.pid = 0
    record.app_name = ""

    # フィルターを実行
    result = syslog_context_filter(record)

    # 戻り値が True であること
    assert result is True

    # 追加された各属性値の検証
    assert hasattr(record, "syslog_time")
    assert isinstance(record.syslog_time, str)
    # ISO 8601 形式のタイムスタンプが含まれているか（例: 2026-08-14T...）
    assert "T" in record.syslog_time

    assert record.hostname == socket.gethostname()
    assert record.pid == os.getpid()

    # app_name 属性が存在し, 文字列であることを確認
    assert hasattr(record, "app_name")
    assert isinstance(record.app_name, str)


@patch("code_chat_cli.logger.APP_NAME", "custom-app")
@patch("code_chat_cli.logger.HOSTNAME", "test-host")
@patch("code_chat_cli.logger.PID", 12345)
def test_syslog_context_filter_mocked_values():
    """正常系: モックされたシステム定数が LogRecord に正しくセットされるか検証."""
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test_path.py",
        lineno=10,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    result = syslog_context_filter(record)

    assert result is True
    assert record.hostname == "test-host"
    assert record.pid == 12345
    assert record.app_name == "custom-app"


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
