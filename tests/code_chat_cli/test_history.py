"""チャット履歴の保存・読み込みおよび readline 設定管理モジュールの単体テスト."""

import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import code_chat_cli.chat
from code_chat_cli.history import (
    save_chat_history,
    save_readline_history,
    setup_readline_history,
)


def test_save_chat_history_success(tmp_path):
    """正常系: 履歴が Markdown 形式でファイルへ保存されるか検証."""
    save_file = tmp_path / "chat_history.md"
    history = ["## User\nHello", "## Model\nHi there!"]

    save_chat_history(str(save_file), history)

    assert save_file.exists()
    assert (
        save_file.read_text(encoding="utf-8") == "## User\nHello\n\n## Model\nHi there!"
    )


def test_save_chat_history_creates_parent_directory(tmp_path):
    """親ディレクトリが存在しない場合, 自動的に生成されて保存されるか検証."""
    nested_file = tmp_path / "logs" / "nested" / "history.md"
    history = ["Message 1", "Message 2"]

    save_chat_history(str(nested_file), history)

    assert nested_file.parent.exists()
    assert nested_file.exists()
    assert nested_file.read_text(encoding="utf-8") == "Message 1\n\nMessage 2"


def test_save_chat_history_exception(tmp_path):
    """異常系: ファイル書き込み時に Exception が発生した場合, except ブロックでキャッチされるか検証."""
    save_file = tmp_path / "error_history.md"
    history = ["Message 1"]

    # write_text 実行時に IOError を発生させる
    with patch.object(Path, "write_text", side_effect=OSError("Disk full")):
        # 例外が発生しても外部に送出されず, 安全に終了することを検証
        save_chat_history(str(save_file), history)


def test_save_readline_history_os_error():
    """write_history_file 実行時に OSError が発生しても pass して正常終了するか検証."""
    mock_readline = MagicMock()
    mock_readline.write_history_file.side_effect = OSError("Disk full")

    mock_history_file = MagicMock()

    with (
        patch("code_chat_cli.history.HAVE_READLINE", True),
        patch("code_chat_cli.history.readline", mock_readline),
        patch("code_chat_cli.history.HISTORY_FILE", mock_history_file),
    ):
        save_readline_history()
        mock_readline.write_history_file.assert_called_once()


def test_setup_readline_history_os_error():
    """read_history_file 実行時に OSError が発生しても pass して正常終了するか検証."""
    mock_readline = MagicMock()
    mock_readline.read_history_file.side_effect = OSError("Permission denied")

    mock_history_file = MagicMock()
    mock_history_file.exists.return_value = True

    with (
        patch("code_chat_cli.history.HAVE_READLINE", True),
        patch("code_chat_cli.history.readline", mock_readline),
        patch("code_chat_cli.history.HISTORY_FILE", mock_history_file),
    ):
        setup_readline_history()
        mock_readline.read_history_file.assert_called_once()


def test_readline_import_primary_success():
    """標準の readline が正常にインポートできるケース."""
    with patch.dict("sys.modules", {"readline": MagicMock()}):
        importlib.reload(code_chat_cli.chat)

    assert code_chat_cli.history.readline is not None


def test_readline_import_both_failed():
    """readline も pyreadline3 もインポートできないケース."""
    orig_import = __import__

    def mock_import(name, *args, **kwargs):
        if name in ("readline", "pyreadline3"):
            raise ImportError(f"No module named '{name}'")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        importlib.reload(code_chat_cli.history)

    assert code_chat_cli.history.readline is None


def test_readline_import_fallback_pyreadline3_success():
    """readline がなく, pyreadline3 がインポートできるケース."""
    orig_import = __import__

    def mock_import(name, *args, **kwargs):
        if name == "readline":
            raise ImportError("No module named 'readline'")
        return orig_import(name, *args, **kwargs)

    mock_pyreadline3 = MagicMock()

    with (
        patch("builtins.__import__", side_effect=mock_import),
        patch.dict("sys.modules", {"pyreadline3": mock_pyreadline3}),
    ):
        importlib.reload(code_chat_cli.history)

    assert code_chat_cli.history.HAVE_READLINE is True
    assert code_chat_cli.history.readline is mock_pyreadline3
