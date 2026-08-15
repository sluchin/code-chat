import subprocess
from subprocess import CalledProcessError
from unittest.mock import patch

import pytest

from code_chat_cli.git_utils import get_git_diff


def test_get_git_diff_staged_exists():
    """ステージング済みの差分がある場合、--cached の結果を返すこと。"""
    with patch("subprocess.check_output") as mock_check_output:
        # 1回目の呼び出し (--cached) で差分を返す
        mock_check_output.return_value = "diff --git a/file.py b/file.py\n+staged code"

        result = get_git_diff()

        assert result == "diff --git a/file.py b/file.py\n+staged code"
        mock_check_output.assert_called_once_with(
            ["git", "diff", "--cached"], text=True, encoding="utf-8"
        )


def test_get_git_diff_unstaged_fallback():
    """ステージング済みの差分がなく、作業ツリーに差分がある場合、git diff の結果を返すこと。"""
    with patch("subprocess.check_output") as mock_check_output:
        # 1回目の呼び出し (--cached) は空文字列、2回目の呼び出し (通常の git diff) で差分を返す
        mock_check_output.side_effect = [
            "",
            "diff --git a/file.py b/file.py\n+unstaged code",
        ]

        result = get_git_diff()

        assert result == "diff --git a/file.py b/file.py\n+unstaged code"
        assert mock_check_output.call_count == 2
        mock_check_output.assert_any_call(
            ["git", "diff", "--cached"], text=True, encoding="utf-8"
        )
        mock_check_output.assert_any_call(["git", "diff"], text=True, encoding="utf-8")


def test_get_git_diff_no_diff():
    """ステージング済み・作業ツリーともに差分がない場合、空文字列を返すこと。"""
    with patch("subprocess.check_output") as mock_check_output:
        mock_check_output.side_effect = ["", ""]

        result = get_git_diff()

        assert result == ""


def test_get_git_diff_called_process_error():
    """git diff コマンドが失敗した場合、CalledProcessError が再送出されること."""
    with patch("subprocess.check_output") as mock_check_output:
        mock_check_output.side_effect = subprocess.CalledProcessError(
            returncode=128, cmd=["git", "diff", "--cached"]
        )

        with pytest.raises(CalledProcessError) as exc_info:
            get_git_diff()

        assert exc_info.value.returncode == 128


@patch("code_chat_cli.git_utils.subprocess.check_output")
def test_get_git_diff_file_not_found_error(mock_check_output):
    """git コマンド不在時に FileNotFoundError が発生することを検証."""
    mock_check_output.side_effect = FileNotFoundError("git command not found")

    with pytest.raises(FileNotFoundError) as exc_info:
        get_git_diff()

    assert "git command not found" in str(exc_info.value)
