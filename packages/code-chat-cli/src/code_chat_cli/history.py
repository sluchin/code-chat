"""チャット履歴の保存・読み込みおよび readline 設定を管理するモジュール."""

from datetime import datetime
from pathlib import Path
from typing import Any

from code_chat_cli.logger import get_logger

# pylint: disable=invalid-name
HAVE_READLINE = False
readline: Any = None

try:
    import readline

    HAVE_READLINE = True
except ImportError:
    try:
        import pyreadline3 as readline  # type: ignore[no-redef]

        HAVE_READLINE = True
    except ImportError:
        pass

logger = get_logger(__name__)

# 履歴ファイルの保存先指定（例: ホームディレクトリ配下）
HISTORY_FILE = Path.home() / ".code_chat_history"
MAX_HISTORY_LENGTH = 1000


def save_chat_history(file_path: str, history: list[str]) -> None:
    """対話ログを指定されたファイルパスへ保存します.

    指定されたパスの親ディレクトリが存在しない場合は自動的に生成し,
    会話履歴を Markdown 形式で書き込みます.

    Args:
        file_path (str): 保存先のファイルパス.
        history (list[str]): 保存対象の対話履歴リスト.
    """
    try:
        path = Path(file_path)
        # 親ディレクトリが存在しない場合は作成
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n\n".join(history), encoding="utf-8")
        logger.info("対話ログを '%s' に保存しました.", file_path)
    except OSError:
        logger.exception("対話ログファイルの保存に失敗しました.")


def setup_readline_history() -> None:
    """コマンド履歴の読み込みと自動保存を設定します."""
    if HAVE_READLINE:
        # 履歴ファイルが存在すれば読み込み
        if HISTORY_FILE.exists() and hasattr(readline, "read_history_file"):
            try:
                readline.read_history_file(str(HISTORY_FILE))
            except OSError:
                pass

        # 履歴の最大保持件数を設定
        if hasattr(readline, "set_history_length"):
            readline.set_history_length(MAX_HISTORY_LENGTH)


def save_readline_history() -> None:
    """コマンド履歴をファイルに書き出します."""
    if HAVE_READLINE and hasattr(readline, "write_history_file"):
        try:
            # ディレクトリがない場合は作成して保存
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            readline.write_history_file(str(HISTORY_FILE))
        except OSError:
            pass


def save_history_if_needed(
    chat_history: list[str], output_file: str | None, auto_save: bool
) -> None:
    """必要に応じて対話履歴をファイルに保存します."""
    if not chat_history:
        return

    target_path = output_file
    if auto_save and not target_path:
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        target_path = f"{timestamp}_chat.md"

    if target_path:
        save_chat_history(target_path, chat_history)
