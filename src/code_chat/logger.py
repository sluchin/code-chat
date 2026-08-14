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
    """LogRecord に syslog スタイルの動的タイムスタンプおよびホスト情報を追加するフィルタ."""
    dt = datetime.fromtimestamp(record.created).astimezone()
    record.syslog_time = dt.isoformat(timespec="microseconds")
    record.hostname = HOSTNAME
    record.pid = PID
    record.app_name = APP_NAME
    return True


def setup_logging(level_name: str = "INFO") -> None:
    """指定されたログレベル名に基づいてアプリケーション全体のロガーを初期化します.

    Args:
        level_name (str, optional): ログレベル文字列 ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL").
            Defaults to "INFO".
    """
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)

    LOG_FORMAT = (
        "%(syslog_time)s %(hostname)s %(app_name)s[%(pid)d]: "
        "%(filename)s:%(lineno)d: %(message)s"
    )

    formatter = logging.Formatter(fmt=LOG_FORMAT)

    # ハンドラを作成し、フィルターを追加する（Logger ではなく Handler に追加）
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    handler.addFilter(syslog_context_filter)

    # ルートロガーのクリアと設定
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.addHandler(handler)

    # サードパーティライブラリのログ制御
    if numeric_level == logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.DEBUG)
        logging.getLogger("google").setLevel(logging.DEBUG)
    else:
        # 通信ログ（httpx）の無駄な出力のみを抑え、アプリ本体のログレベルは全伝播させる
        logging.getLogger("httpx").setLevel(logging.WARNING)
        # google_genai の警告ログまで消してしまうのを防ぐため、WARNING で止めずにルートに委ねるか INFO にする


def get_logger(name: str) -> logging.Logger:
    """モジュールごとのロガーインスタンスを取得します.

    Args:
        name (str): モジュール名（通常は __name__ を指定）.

    Returns:
        logging.Logger: ロガーオブジェクト.
    """
    return logging.getLogger(name)


def suppress_info_logs() -> None:
    """コミットメッセージ生成時など、標準出力のノイズを減らすため INFO ログを抑制する."""
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("code_chat").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
