"""アプリケーション共通のロガー設定モジュール."""

import logging
import os
import socket
import sys
from datetime import datetime
from pathlib import Path

# システム固定情報（ホスト名およびプロセスID）
HOSTNAME = socket.gethostname()
PID = os.getpid()
APP_NAME = Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "python"


def syslog_context_filter(record: logging.LogRecord) -> bool:
    """LogRecord に syslog スタイルの動的タイムスタンプおよびホスト情報を追加するフィルタ.

    Args:
        record (logging.LogRecord): 処理対象のログレコード.

    Returns:
        bool: 常に True（レコードを常に処理対象とする）.

    """
    dt = datetime.fromtimestamp(record.created).astimezone()
    record.syslog_time = dt.isoformat(timespec="microseconds")
    record.hostname = HOSTNAME
    record.pid = PID
    record.app_name = APP_NAME
    return True


def setup_logging(level_name: str = "INFO", trace: bool = False) -> None:
    """指定されたログレベル名に基づいてアプリケーション全体のロガーを初期化します.

    Args:
        level_name (str, optional): ログレベル文字列 ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL").
            Defaults to "INFO".
        trace (bool, optional): ライブラリ内部通信ログを出力するかどうか. Defaults to False.

    """
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)

    log_format = (
        "%(syslog_time)s %(hostname)s %(app_name)s[%(pid)d]: "
        "%(filename)s:%(lineno)d: %(message)s"
    )

    formatter = logging.Formatter(fmt=log_format)

    # ハンドラを作成し, フィルターを追加する（Logger ではなく Handler に追加）
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    handler.addFilter(syslog_context_filter)
    handler.setLevel(numeric_level)

    # ルートロガーのクリアと設定
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.addHandler(handler)

    # アプリケーション固有のロガー（code_chat_cli）のレベルも明示的に変更する
    app_logger = logging.getLogger("code_chat_cli")
    app_logger.setLevel(numeric_level)

    # サードパーティ製ライブラリのログ制御
    third_party_loggers = ["httpx", "httpcore", "google", "urllib3"]

    if trace:
        # --trace が指定されている場合のみ, ライブラリの DEBUG / TRACE ログを出す
        for logger_name in third_party_loggers:
            logging.getLogger(logger_name).setLevel(logging.DEBUG)
    else:
        # 通常時 (-D / --log-level DEBUG の場合含む) はサードパーティの通信ログを抑制
        for logger_name in third_party_loggers:
            logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """モジュールごとのロガーインスタンスを取得します.

    Args:
        name (str): モジュール名（通常は __name__ を指定）.

    Returns:
        logging.Logger: ロガーオブジェクト.

    """
    return logging.getLogger(name)


def suppress_info_logs() -> None:
    """コミットメッセージ生成時など, 標準出力のノイズを減らすため INFO ログを抑制します."""
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("code_chat_cli").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
