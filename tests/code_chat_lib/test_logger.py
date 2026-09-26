"""`code_chat_lib.logger` モジュールにおけるログフォーマット, 出力レベル設定, およびファイル出力のテスト."""

import logging
import os
import socket
from unittest.mock import patch

import pytest
from google.genai.errors import APIError

from code_chat_lib.logger import (
    THIRD_PARTY_LOGGERS,
    _is_trace_enabled,
    _syslog_context_filter,
    get_logger,
    log_exception,
    set_trace,
    setup_logging,
)


@pytest.fixture
def trace_off():
    """テストの前後で --trace を無効に戻す (サードパーティのロガーの状態を引き継がない)."""
    set_trace(False)
    yield
    set_trace(False)


class TestSyslogContextFilter:
    """`_syslog_context_filter` のテスト."""

    def test_syslog_context_filter_success(self):
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
        result = _syslog_context_filter(record)

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

    @patch("code_chat_lib.logger.APP_NAME", "custom-app")
    @patch("code_chat_lib.logger.HOSTNAME", "test-host")
    @patch("code_chat_lib.logger.PID", 12345)
    def test_syslog_context_filter_mocked_values_success(self):
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

        result = _syslog_context_filter(record)

        assert result is True
        assert record.hostname == "test-host"
        assert record.pid == 12345
        assert record.app_name == "custom-app"


class TestSetupLogging:
    """`setup_logging` のテスト."""

    @pytest.mark.parametrize(
        "name",
        [
            "code_chat_cli.chat",
            "code_chat_lib.api",
            "code_chat_mcp.mcp_service",
            "code_chat_rag.indexer",
        ],
    )
    def test_setup_logging_root_level_applies_to_all_packages_success(self, name):
        """setup_logging が, ルートロガーと handler のレベルを更新し, 全パッケージのロガーがそれを継承するか検証."""
        setup_logging("DEBUG")

        root_logger = logging.getLogger()

        assert root_logger.level == logging.DEBUG
        assert logging.getLogger(name).getEffectiveLevel() == logging.DEBUG
        assert len(root_logger.handlers) > 0
        assert root_logger.handlers[0].level == logging.DEBUG

    def test_setup_logging_level_success(self, capsys):
        """ログレベルのセットアップが正常に反映されるか検証."""
        setup_logging(level_name="DEBUG")
        logger = get_logger("test_module")

        logger.debug("デバッグメッセージテスト")
        logger.info("インフォメッセージテスト")

        captured = capsys.readouterr()
        assert "デバッグメッセージテスト" in captured.err
        assert "インフォメッセージテスト" in captured.err

    def test_setup_logging_info_log_only_success(self, capsys):
        """INFO レベル設定時に DEBUG ログが出力されないか検証."""
        setup_logging(level_name="INFO")
        logger = get_logger("test_module")

        logger.debug("このログは出力されないはず")
        logger.info("このログは出力される")

        captured = capsys.readouterr()
        assert "このログは出力されないはず" not in captured.err
        assert "このログは出力される" in captured.err

    def test_setup_logging_trace_enables_third_party_logs_success(self):
        """trace=True の場合はサードパーティのログが DEBUG になり, 通常時は WARNING に抑制されるか検証."""
        names = ["httpx", "httpcore", "google", "urllib3"]

        setup_logging("INFO", trace=True)
        assert all(logging.getLogger(n).level == logging.DEBUG for n in names)

        setup_logging("INFO", trace=False)
        assert all(logging.getLogger(n).level == logging.WARNING for n in names)


class TestSetTrace:
    """`set_trace` のテスト."""

    @pytest.mark.usefixtures("trace_off")
    def test_set_trace_success(self):
        """有効時はサードパーティのロガーが DEBUG, 無効時は WARNING になるか検証."""
        set_trace(True)
        assert all(
            logging.getLogger(n).level == logging.DEBUG for n in THIRD_PARTY_LOGGERS
        )

        set_trace(False)
        assert all(
            logging.getLogger(n).level == logging.WARNING for n in THIRD_PARTY_LOGGERS
        )


class TestIsTraceEnabled:
    """`_is_trace_enabled` のテスト."""

    @pytest.mark.usefixtures("trace_off")
    def test_is_trace_enabled_success(self):
        """set_trace の設定が反映されるか検証."""
        set_trace(True)
        assert _is_trace_enabled() is True

        set_trace(False)
        assert _is_trace_enabled() is False

    @pytest.mark.usefixtures("trace_off")
    def test_is_trace_enabled_unset(self):
        """set_trace を呼んでいない (ロガーが NOTSET の) 場合は, 無効として扱われるか検証."""
        for name in THIRD_PARTY_LOGGERS:
            logging.getLogger(name).setLevel(logging.NOTSET)

        assert _is_trace_enabled() is False


class TestLogException:
    """`log_exception` のテスト."""

    @pytest.mark.usefixtures("trace_off")
    def test_log_exception_gemini_error_detail_success(self, caplog):
        """Gemini API のエラーの詳細 (レスポンス全体) は, DEBUG ログにだけ出力されるか検証."""
        logger = get_logger("test_log_exception")

        with caplog.at_level(logging.INFO, logger="test_log_exception"):
            try:
                raise APIError(400, {"error": {"message": "API key not valid"}})
            except APIError:
                log_exception(logger, "処理に失敗しました")
        assert "エラーの詳細" not in caplog.text

        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="test_log_exception"):
            try:
                raise APIError(400, {"error": {"message": "API key not valid"}})
            except APIError:
                log_exception(logger, "処理に失敗しました")
        assert "エラーの詳細" in caplog.text
        assert "API key not valid" in caplog.text

    @pytest.mark.usefixtures("trace_off")
    def test_log_exception_gemini_error_success(self, caplog):
        """Gemini API のエラーは, --trace なしではトレースバックを省き, エラー内容だけが出力されるか検証."""
        logger = get_logger("test_log_exception")

        with caplog.at_level(logging.ERROR, logger="test_log_exception"):
            try:
                raise self._gemini_error()
            except APIError:
                log_exception(logger, "処理 (%s) に失敗しました", "list")

        record = caplog.records[0]
        assert record.exc_info is None
        assert "処理 (list) に失敗しました: " in record.getMessage()
        assert "[HTTP 400" in record.getMessage()
        assert "API キーが無効です" in record.getMessage()
        assert "ヒント: " in record.getMessage()

    @pytest.mark.usefixtures("trace_off")
    def test_log_exception_gemini_error_trace_success(self, caplog):
        """--trace 指定時は, Gemini API のエラーでもトレースバックが出力されるか検証."""
        logger = get_logger("test_log_exception")
        set_trace(True)

        with caplog.at_level(logging.ERROR, logger="test_log_exception"):
            try:
                raise self._gemini_error()
            except APIError:
                log_exception(logger, "処理に失敗しました")

        assert caplog.records[0].exc_info is not None
        assert "Traceback" in caplog.text

    @pytest.mark.usefixtures("trace_off")
    def test_log_exception_other_error_success(self, caplog):
        """Gemini API 以外のエラーは, --trace なしでもトレースバックが出力されるか検証."""
        logger = get_logger("test_log_exception")

        with caplog.at_level(logging.ERROR, logger="test_log_exception"):
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                log_exception(logger, "処理に失敗しました")

        assert caplog.records[0].exc_info is not None

    @pytest.mark.usefixtures("trace_off")
    def test_log_exception_file_not_found_success(self, caplog):
        """FileNotFoundError は, --trace なしではトレースバックを省き, -D でだけ出力されるか検証."""
        logger = get_logger("test_log_exception")

        with caplog.at_level(logging.INFO, logger="test_log_exception"):
            try:
                raise FileNotFoundError("ディレクトリが存在しません: /no/such")
            except FileNotFoundError:
                log_exception(logger, "処理に失敗しました")

        record = caplog.records[0]
        assert record.exc_info is None
        assert "処理に失敗しました: ディレクトリが存在しません" in record.getMessage()
        assert "Traceback" not in caplog.text

        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="test_log_exception"):
            try:
                raise FileNotFoundError("x")
            except FileNotFoundError:
                log_exception(logger, "処理に失敗しました")
        assert "Traceback" in caplog.text

    @pytest.mark.usefixtures("trace_off")
    def test_log_exception_file_not_found_trace_success(self, caplog):
        """--trace 指定時は, FileNotFoundError でもトレースバックが出力されるか検証."""
        logger = get_logger("test_log_exception")
        set_trace(True)

        with caplog.at_level(logging.ERROR, logger="test_log_exception"):
            try:
                raise FileNotFoundError("x")
            except FileNotFoundError:
                log_exception(logger, "処理に失敗しました")

        assert caplog.records[0].exc_info is not None

    @pytest.mark.usefixtures("trace_off")
    def test_log_exception_wrapped_gemini_error_success(self, caplog):
        """Gemini API のエラーを別の例外で包んでいる場合も, トレースバックが省かれるか検証."""
        logger = get_logger("test_log_exception")

        with caplog.at_level(logging.ERROR, logger="test_log_exception"):
            try:
                try:
                    raise self._gemini_error()
                except APIError as e:
                    raise RuntimeError("wrapped") from e
            except RuntimeError:
                log_exception(logger, "処理に失敗しました")

        assert caplog.records[0].exc_info is None

    @staticmethod
    def _gemini_error() -> APIError:
        return APIError(400, {"error": {"message": "API key not valid"}})
