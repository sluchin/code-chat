"""アプリケーション共通のロガー設定モジュール."""

from datetime import datetime
import logging
import os
from pathlib import Path
import socket
import sys

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
    # 文字列から logging の数値定数を取得（不正な値の場合は INFO にフォールバック）
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)

    # syslog 風フォーマットの設定
    # 例: 2026-08-14T11:20:05.987654+09:00 hostname code-chat[12345]: chat.py:42: メッセージ
    LOG_FORMAT = (
        "%(syslog_time)s %(hostname)s %(app_name)s[%(pid)d]: "
        "%(filename)s:%(lineno)d: %(message)s"
    )

    formatter = logging.Formatter(fmt=LOG_FORMAT)

    # 標準エラー出力 (sys.stderr) へ出力するハンドラ
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    # ルートロガーに対して基本設定を適用
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # 重複出力を防ぐため既存のハンドラとフィルタをクリア
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.filters.clear()

    # syslog コンテキスト付与用のフィルタを追加 (1度のみ追加され、以降全ログで動的評価される)
    root_logger.addFilter(syslog_context_filter)
    root_logger.addHandler(handler)

    # サードパーティライブラリのログレベル制御
    if numeric_level == logging.DEBUG:
        # デバッグモード時は httpx や google_genai の詳細ログを表示
        logging.getLogger("httpx").setLevel(logging.DEBUG)
        logging.getLogger("google_genai").setLevel(logging.DEBUG)
    else:
        # 通常時は WARNING 以上（エラー時のみ）にして通信ログや AFC などの INFO ログを抑制
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("google_genai").setLevel(logging.WARNING)


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
