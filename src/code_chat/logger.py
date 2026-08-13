"""アプリケーション共通のロガー設定モジュール."""

import logging
import sys


def setup_logging(level_name: str = "INFO") -> None:
    """指定されたログレベル名に基づいてアプリケーション全体のロガーを初期化します.

    Args:
        level_name (str, optional): ログレベル文字列 ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL").
            Defaults to "INFO".
    """
    # 文字列から logging の数値定数を取得（不正な値の場合は INFO にフォールバック）
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="[%(levelname)s] %(asctime)s - %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # 標準エラー出力 (sys.stderr) へ出力するハンドラ
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    # ルートロガーに対して基本設定を適用
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # 重複出力を防ぐため既存のハンドラをクリア
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.addHandler(handler)

    # httpx のログレベル制御
    if numeric_level == logging.DEBUG:
        # デバッグモード時は httpx の通信ログ（GET/POSTリクエスト等）を表示
        logging.getLogger("httpx").setLevel(logging.DEBUG)
    else:
        # 通常時は WARNING 以上（エラー時のみ）にして通信ログを消す
        logging.getLogger("httpx").setLevel(logging.WARNING)


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
