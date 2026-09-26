"""アプリケーション共通のロガー設定モジュール."""

import logging
import os
import socket
import sys
from datetime import datetime
from pathlib import Path

from code_chat_lib.gemini_error import find_api_error, format_error

# システム固定情報（ホスト名およびプロセスID）
HOSTNAME = socket.gethostname()
PID = os.getpid()
APP_NAME = Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "python"

# --trace 指定時に DEBUG にする, サードパーティ製ライブラリのロガー
THIRD_PARTY_LOGGERS = ("httpx", "httpcore", "google", "urllib3")


def _syslog_context_filter(record: logging.LogRecord) -> bool:
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
    handler.addFilter(_syslog_context_filter)
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

    set_trace(trace)


def set_trace(enabled: bool) -> None:
    """--trace の有効・無効を設定します.

    有効時は, サードパーティ製ライブラリの DEBUG / TRACE ログを出力し, Gemini API のエラーでも
    トレースバックを出力します (`log_exception` を参照). 無効時は, 通信ログを抑制します
    (-D / --log-level DEBUG の場合を含む).

    Args:
        enabled (bool): --trace が指定されているかどうか.

    """
    level = logging.DEBUG if enabled else logging.WARNING
    for logger_name in THIRD_PARTY_LOGGERS:
        logging.getLogger(logger_name).setLevel(level)


def _is_trace_enabled() -> bool:
    """--trace が有効かどうかを返します (`set_trace` で DEBUG にしたロガーの有無で判定).

    Returns:
        bool: --trace が有効な場合は True.

    """
    return all(
        logging.getLogger(name).level == logging.DEBUG for name in THIRD_PARTY_LOGGERS
    )


def log_exception(logger: logging.Logger, message: str, *args: object) -> None:
    """処理中の例外をログに出力します. Gemini API のエラーは, 概要とヒントに整理し, トレースバックを省きます.

    Gemini API のエラー (認証エラー, モデル未提供, 上限超過など) は, トレースバックを見ても
    原因が分からないため, 概要 (HTTP ステータス, 原因) と対処のヒントだけを出力します.
    レスポンスの詳細は -D (DEBUG), トレースバックは --trace 指定時に出力します.
    ファイルやディレクトリが見つからないエラー (`FileNotFoundError`) は, パスの指定ミスなど,
    原因が明らかなため, --trace 指定時を除いて, トレースバックを省きます (詳細は -D で出力します).
    それ以外の例外は, 常にトレースバック付きです.
    `except` ブロックの中から呼び出してください.

    Args:
        logger (logging.Logger): 出力先のロガー.
        message (str): ログメッセージ (`%s` などのプレースホルダーを含めてよい).
        *args (object): メッセージに埋め込む値.

    """
    error = sys.exc_info()[1]
    api_error = find_api_error(error)
    if api_error is None:
        if isinstance(error, FileNotFoundError) and not _is_trace_enabled():
            logger.error(message + ": %s", *args, error)
            logger.debug("エラーの詳細", exc_info=error)
            return
        logger.exception(message, *args)
        return

    detail = format_error(api_error)
    if _is_trace_enabled():
        logger.exception(message + ": %s", *args, detail)
        return

    logger.error(message + ": %s", *args, detail)
    logger.debug("エラーの詳細: %s", api_error)


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
